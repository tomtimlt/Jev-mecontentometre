#!/usr/bin/env python3
"""Compare plusieurs structures de requête Jev sur un jeu de commentaires étiquetés à la main.

Usage : python3 eval/compare_prompts.py eval/apple_ipad_crush.json [--runs 2]
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_comments as jc  # noqa: E402


def unhappy_question(target, extra=""):
    q = jc.build_questions(target, with_context=False)["is_unhappy"]
    return {"is_unhappy": {**q, "instructions": q["instructions"] + extra}}


def summary(meta):
    """Premier paragraphe de la description : en général le résumé, avant les liens et le boilerplate."""
    first = meta["description"].strip().split("\n\n")[0]
    return first[:500]


def variants(meta, target):
    ctx = f'YouTube video "{meta["title"]}" by {meta["channel"]}.'
    ctx_sum = f"{ctx}\nVideo summary: {summary(meta)}"
    about = " Judge only the comment, using the video context to understand what it refers to."
    return {
        "A. commentaire seul": lambda t: (t, unhappy_question(target)),
        "B. + titre (state)": lambda t: (f"{ctx}\n\nComment: {t}", unhappy_question(target, about)),
        "C. + titre + résumé (state)": lambda t: (f"{ctx_sum}\n\nComment: {t}", unhappy_question(target, about)),
        "D. résumé dans les instructions": lambda t: (
            t, unhappy_question(target, f" Context: this is a comment under the {ctx_sum}")),
    }


def ask(state, questions, key):
    import urllib.request
    body = json.dumps({"state": state, "model": "jev-latest", "questions": questions}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(jc.JEV_URL, data=body, method="POST", headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            return d["answers"]["is_unhappy"]["noul"], d["usage"]["input_tokens"]
        except Exception:
            if attempt == 4:
                raise
            import time
            time.sleep(2 ** attempt)


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dataset")
    p.add_argument("--runs", type=int, default=1, help="répétitions pour mesurer la variance")
    args = p.parse_args()
    ds = json.load(open(args.dataset, encoding="utf-8"))
    yt_key, jev_key = os.environ["Youtube_V3"], os.environ["TYPESAFE_API_KEY"]

    raw = jc.yt_get("videos", yt_key, part="snippet", id=ds["video_id"])["items"][0]["snippet"]
    meta = {"title": raw["title"], "channel": raw["channelTitle"], "description": raw.get("description", "")}
    items, labels = ds["items"], [i["label"] for i in ds["items"]]
    print(f"{len(items)} commentaires étiquetés ({sum(labels)} mécontents) — cible : {ds['target']}\n")

    results = {}
    with cf.ThreadPoolExecutor(16) as ex:
        for name, build in variants(meta, ds["target"]).items():
            runs = []
            for _ in range(args.runs):
                out = list(ex.map(lambda it: ask(*build(it["text"]), jev_key), items))
                runs.append(out)
            results[name] = runs

    print(f"{'Variante':<34} {'Exactitude':>10} {'AUC':>6} {'FP':>4} {'FN':>4} {'Tokens/req':>11}")
    for name, runs in results.items():
        for r in runs:
            scores = [s for s, _ in r]
            pred = [s >= jc.THRESHOLD for s in scores]
            acc = sum(p == bool(l) for p, l in zip(pred, labels)) / len(labels)
            fp = sum(p and not l for p, l in zip(pred, labels))
            fn = sum(l and not p for p, l in zip(pred, labels))
            tok = sum(t for _, t in r) / len(r)
            print(f"{name:<34} {acc:>9.0%} {auc(scores, labels):>6.2f} {fp:>4} {fn:>4} {tok:>11.0f}")
    out = Path(args.dataset).with_suffix(".results.json")
    json.dump({name: [[s for s, _ in r] for r in runs] for name, runs in results.items()},
              open(out, "w"), indent=1)


if __name__ == "__main__":
    main()
