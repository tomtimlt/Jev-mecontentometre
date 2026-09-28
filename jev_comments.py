#!/usr/bin/env python3
"""Mesure le pourcentage de mécontents dans les commentaires d'une vidéo YouTube.

Récupère les commentaires via l'API YouTube Data v3, fait noter chacun par Jev
(TypeSafe System One), puis agrège : % de mécontents et raisons du mécontentement.

Variables d'environnement : Youtube_V3 (clé YouTube Data v3), TYPESAFE_API_KEY (clé Jev).

Usage : python3 jev_comments.py <url-ou-id-video> [--max 1000] [--json rapport.json]
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

JEV_URL = "https://api.typesafe.ai/v1/systemone"
YT_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
THRESHOLD = 0.5

# Raisons du mécontentement : n'ont de sens que pour les commentaires mécontents.
REASONS = {
    "content": "Criticizes the substance of the video: wrong, shallow, boring, misleading or low-effort content.",
    "creator": "Criticizes the creator or company personally, their behavior, values or decisions.",
    "ads": "Complains about sponsorship, ads, product placement or commercial intent.",
    "clickbait": "Complains about clickbait, misleading title or thumbnail.",
    "technical": "Complains about audio, video quality, editing, length or pacing.",
}
REASON_LABELS = {
    "content": "Fond / contenu",
    "creator": "Créateur / marque",
    "ads": "Pub / sponsoring",
    "clickbait": "Clickbait",
    "technical": "Technique (son, montage, durée)",
}
DEFAULT_TARGET = "the video or its creator"


def build_questions(target):
    questions = {
        "is_relevant": {
            "type": "noul",
            "instructions": "Is this a genuine comment reacting to the video (not spam, self-promotion or bot)?",
        },
        "is_unhappy": {
            "type": "noul",
            "instructions": f"Is the commenter genuinely unhappy with {target}?",
            "criteria": {
                "true": f"Sincerely expresses dissatisfaction, disappointment, anger or criticism aimed at {target}, "
                        "including sarcasm used to criticize",
                "false": f"Neutral or positive about {target}; criticism aimed at someone else (e.g. at other "
                         "commenters or critics); or playful jokes, memes and running gags where the commenter is amused",
            },
        },
    }
    for key, text in REASONS.items():
        questions[f"reason_{key}"] = {
            "type": "noul",
            "instructions": f"Does the comment contain this complaint about {target}? {text}",
        }
    return questions




def video_id(arg):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})", arg)
    return m.group(1) if m else arg


def fetch_comments(vid, key, limit):
    comments, token = [], None
    while len(comments) < limit:
        params = {"part": "snippet", "videoId": vid, "maxResults": 100,
                  "textFormat": "plainText", "order": "relevance", "key": key}
        if token:
            params["pageToken"] = token
        try:
            with urllib.request.urlopen(f"{YT_URL}?{urllib.parse.urlencode(params)}") as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            sys.exit(f"Erreur YouTube {e.code} : {e.read().decode()[:300]}")
        for item in data.get("items", []):
            s = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({"text": s["textDisplay"], "likes": s.get("likeCount", 0)})
        token = data.get("nextPageToken")
        if not token:
            break
    return comments[:limit]


def score(text, key, questions, retries=5):
    body = json.dumps({"state": text[:4000], "model": "jev-latest", "questions": questions}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(JEV_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            answers = {k: v["noul"] for k, v in data["answers"].items()}
            return answers, data.get("usage", {})
        except urllib.error.HTTPError as e:
            if e.code in (429, 529, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def score_all(comments, key, questions, workers):
    usage = {"input_tokens": 0, "output_tokens": 0}
    failed = 0
    done = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futures = {ex.submit(score, c["text"], key, questions): c for c in comments}
        for f in cf.as_completed(futures):
            c = futures[f]
            try:
                c["scores"], u = f.result()
                for k in usage:
                    usage[k] += u.get(k, 0)
            except Exception as e:
                c["error"] = str(e)
                failed += 1
            done += 1
            print(f"\rNotation Jev : {done}/{len(comments)}", end="", file=sys.stderr)
    print(file=sys.stderr)
    return usage, failed


def report(comments):
    scored = [c for c in comments if "scores" in c]
    relevant = [c for c in scored if c["scores"]["is_relevant"] >= THRESHOLD]
    unhappy = [c for c in relevant if c["scores"]["is_unhappy"] >= THRESHOLD]
    n = len(relevant) or 1
    likes_total = sum(c["likes"] + 1 for c in relevant) or 1
    reasons = {}
    for key in REASONS:
        hits = [c for c in unhappy if c["scores"][f"reason_{key}"] >= THRESHOLD]
        reasons[key] = {"count": len(hits), "pct_of_unhappy": 100 * len(hits) / (len(unhappy) or 1)}
    top = sorted(unhappy, key=lambda c: (c["likes"], c["scores"]["is_unhappy"]), reverse=True)[:5]
    return {
        "comments_scored": len(scored),
        "spam_or_offtopic": len(scored) - len(relevant),
        "relevant": len(relevant),
        "unhappy": len(unhappy),
        "pct_unhappy": 100 * len(unhappy) / n,
        "pct_unhappy_like_weighted": 100 * sum(c["likes"] + 1 for c in unhappy) / likes_total,
        "mean_unhappy_score": sum(c["scores"]["is_unhappy"] for c in relevant) / n,
        "reasons": reasons,
        "top_unhappy": [{"text": c["text"][:200], "likes": c["likes"],
                         "score": c["scores"]["is_unhappy"]} for c in top],
    }


def print_report(vid, target, r, usage, failed, elapsed):
    print(f"\n=== Vidéo {vid} — mécontentement envers : {target} ===")
    print(f"Commentaires notés    : {r['comments_scored']} (échecs : {failed}) en {elapsed:.1f} s")
    print(f"Spam / hors sujet     : {r['spam_or_offtopic']} (exclus)")
    print(f"\n>>> Mécontents        : {r['pct_unhappy']:.1f} %  ({r['unhappy']}/{r['relevant']})")
    print(f"    Pondéré par likes : {r['pct_unhappy_like_weighted']:.1f} %")
    print(f"    Score moyen       : {r['mean_unhappy_score']:.2f}")
    print("\nRaisons (part des mécontents, cumulables) :")
    for key, v in sorted(r["reasons"].items(), key=lambda kv: -kv[1]["count"]):
        bar = "█" * round(v["pct_of_unhappy"] / 4)
        print(f"  {REASON_LABELS[key]:<32} {v['pct_of_unhappy']:5.1f} %  {bar}")
    print("\nMécontents les plus likés :")
    for c in r["top_unhappy"]:
        print(f"  [{c['likes']:>6} 👍 | {c['score']:.2f}] {c['text'][:120]!r}")
    print(f"\nTokens Jev : {usage['input_tokens']} in / {usage['output_tokens']} out")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video", help="URL ou ID de la vidéo YouTube")
    p.add_argument("--target", default=DEFAULT_TARGET,
                   help='contre qui mesurer le mécontentement, ex. "Apple" (défaut : la vidéo ou son créateur)')
    p.add_argument("--max", type=int, default=500, help="nombre max de commentaires (défaut 500)")
    p.add_argument("--workers", type=int, default=16, help="requêtes Jev en parallèle (défaut 16)")
    p.add_argument("--json", help="écrire le rapport + scores détaillés dans ce fichier")
    args = p.parse_args()

    yt_key, jev_key = os.environ.get("Youtube_V3"), os.environ.get("TYPESAFE_API_KEY")
    if not yt_key or not jev_key:
        sys.exit("Variables Youtube_V3 et TYPESAFE_API_KEY requises.")

    vid = video_id(args.video)
    comments = fetch_comments(vid, yt_key, args.max)
    if not comments:
        sys.exit("Aucun commentaire trouvé (désactivés ?).")
    print(f"{len(comments)} commentaires récupérés.", file=sys.stderr)

    t0 = time.time()
    usage, failed = score_all(comments, jev_key, build_questions(args.target), args.workers)
    r = report(comments)
    print_report(vid, args.target, r, usage, failed, time.time() - t0)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"video": vid, "target": args.target, "report": r, "usage": usage, "comments": comments},
                      f, ensure_ascii=False, indent=1)
        print(f"Détails écrits dans {args.json}")


if __name__ == "__main__":
    main()
