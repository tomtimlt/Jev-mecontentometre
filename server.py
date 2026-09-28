#!/usr/bin/env python3
"""Dashboard web pour jev_comments : python3 server.py [--port 8000] puis http://localhost:8000

Les clés API restent côté serveur (variables Youtube_V3 et TYPESAFE_API_KEY) ;
le navigateur ne voit que les résultats. Chaque analyse est enregistrée dans runs/.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import jev_comments as jc

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
RUNS = ROOT / "runs"
MAX_COMMENTS = 2000


def run_analysis(video, target, limit, emit):
    yt_key, jev_key = os.environ.get("Youtube_V3"), os.environ.get("TYPESAFE_API_KEY")
    if not yt_key or not jev_key:
        raise RuntimeError("Variables Youtube_V3 et TYPESAFE_API_KEY requises côté serveur.")
    vid = jc.video_id(video)
    emit("status", {"message": "Récupération de la vidéo…"})
    meta = jc.fetch_video(vid, yt_key)
    emit("video", meta)
    emit("status", {"message": "Récupération des commentaires…"})
    comments = jc.fetch_comments(vid, yt_key, limit)
    if not comments:
        raise RuntimeError("Aucun commentaire trouvé (commentaires désactivés ?).")
    emit("status", {"message": f"Notation de {len(comments)} commentaires par Jev…"})

    lock = threading.Lock()
    last = [0.0]

    def progress(done, total):
        with lock:
            now = time.time()
            if done == total or now - last[0] > 0.15:
                last[0] = now
                emit("progress", {"done": done, "total": total})

    t0 = time.time()
    context = jc.video_context(meta)
    usage, failed = jc.score_all(comments, jev_key, jc.build_questions(target), 16, progress, context)
    run = {
        "id": time.strftime("%Y%m%d-%H%M%S") + "-" + vid,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "video": meta,
        "target": target,
        "context": context,
        "threshold": jc.THRESHOLD,
        "reason_labels": jc.REASON_LABELS,
        "report": jc.report(comments),
        "usage": usage,
        "failed": failed,
        "elapsed": round(time.time() - t0, 1),
        "comments": comments,
    }
    RUNS.mkdir(exist_ok=True)
    (RUNS / f"{run['id']}.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    return run


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/analyze":
            return self.analyze(parse_qs(url.query))
        if url.path == "/api/runs":
            return self.list_runs()
        m = re.fullmatch(r"/api/runs/([\w-]+)", url.path)
        if m:
            f = RUNS / f"{m.group(1)}.json"
            if not f.is_file():
                return self.send_json({"error": "Analyse introuvable"}, 404)
            return self.send_json(json.loads(f.read_text(encoding="utf-8")))
        return super().do_GET()

    def list_runs(self):
        runs = []
        for f in sorted(RUNS.glob("*.json"), reverse=True) if RUNS.is_dir() else []:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            runs.append({"id": d["id"], "created": d["created"], "title": d["video"]["title"],
                         "target": d["target"], "pct_unhappy": d["report"]["pct_unhappy"],
                         "count": d["report"]["comments_scored"]})
        self.send_json(runs)

    def analyze(self, q):
        video = (q.get("video") or [""])[0].strip()
        target = (q.get("target") or [""])[0].strip() or jc.DEFAULT_TARGET
        try:
            limit = max(1, min(MAX_COMMENTS, int((q.get("max") or ["300"])[0])))
        except ValueError:
            limit = 300
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        lock = threading.Lock()

        def emit(event, data):
            msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
            with lock:
                self.wfile.write(msg)
                self.wfile.flush()

        try:
            if not video:
                raise RuntimeError("Indique une URL ou un ID de vidéo.")
            emit("done", run_analysis(video, target, limit, emit))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                emit("fail", {"message": str(e)})
            except OSError:
                pass


def main():
    p = argparse.ArgumentParser(description="Dashboard web jev_comments")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    print(f"Dashboard : http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
