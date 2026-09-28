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
YT_API = "https://www.googleapis.com/youtube/v3"
THRESHOLD = 0.5

# Raisons du mécontentement : n'ont de sens que pour les commentaires mécontents.
REASONS = {
    "content": "Criticizes the substance of the video: wrong, shallow, boring, misleading or low-effort content.",
    "behavior": "Criticizes their behavior, attitude, values or decisions (a controversy, pricing, how they treat people, ethics), not the video's content, humor or form.",
    "ads": "Complains about sponsor segments, ads or product placement inside this video itself. Criticizing an advertisement that is the subject of the video does not count.",
    "clickbait": "Complains about clickbait, misleading title or thumbnail.",
    "technical": "Complains about audio, video quality, editing, length or pacing.",
}
REASON_LABELS = {
    "content": "Fond / contenu",
    "behavior": "Comportement / valeurs",
    "ads": "Pub / sponsoring",
    "clickbait": "Clickbait",
    "technical": "Technique (son, montage, durée)",
}
DEFAULT_TARGET = "the video or its creator"


CONTEXT_HINT = " Judge only the comment, using the video context to understand what it refers to."


SUMMARY_QUESTION = {
    "describes_video": {
        "type": "noul",
        "instructions": "Does this text describe what this specific video is about (its topic, story or news)?",
        "criteria": {
            "true": "Summarizes the subject or content of the video",
            "false": "Social media links, equipment, FAQ, credits, disclaimers, sponsor codes or other channel boilerplate",
        },
    },
}


def description_summary(description, jev_key, title="", limit=500, max_candidates=6, budget=14.0):
    """Premier paragraphe de la description que Jev juge descriptif du contenu de la vidéo.

    Les descriptions YouTube sont souvent remplies de liens, matériel ou FAQ : envoyer ça
    comme contexte embrouille Jev. Renvoie "" si aucun paragraphe ne décrit la vidéo.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n-{5,}\n?", description or "")]
    paras = [p for p in paras if sum(ch.isalpha() for ch in p) >= 30][:max_candidates]
    if not paras:
        return ""

    def judge(para):
        state = f'Title of the video: "{title}"\n\nText from its description:\n{para[:1500]}'
        try:
            return score_state(state, jev_key, SUMMARY_QUESTION, retries=4, timeout=3)[0]["describes_video"]
        except Exception:
            return 0.0

    # En parallèle, et on garde le premier paragraphe (dans l'ordre) validé par Jev.
    # La latence de Jev varie (0,3 s à 15 s) : au-delà du budget, on se contente du titre.
    ex = cf.ThreadPoolExecutor(len(paras))
    futures = [ex.submit(judge, p) for p in paras]
    deadline = time.time() + budget
    try:
        for para, fut in zip(paras, futures):
            try:
                if fut.result(timeout=max(0, deadline - time.time())) >= THRESHOLD:
                    return " ".join(para.split())[:limit]
            except cf.TimeoutError:
                return ""
        return ""
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def video_context(meta, jev_key):
    """Contexte donné à Jev avec chaque commentaire : titre, chaîne et résumé de la vidéo.

    Mesuré dans eval/ : 79 % -> 95 % d'exactitude sur des commentaires ambigus.
    """
    ctx = f'YouTube video "{meta["title"]}" by {meta["channel"]}.'
    summary = description_summary(meta.get("description", ""), jev_key, meta["title"])
    return f"{ctx}\nVideo summary: {summary}" if summary else ctx


def build_questions(target, with_context=True):
    hint = CONTEXT_HINT if with_context else ""
    questions = {
        "is_relevant": {
            "type": "noul",
            "instructions": "Is this a genuine comment reacting to the video (not spam, self-promotion or bot)?",
        },
        "is_unhappy": {
            "type": "noul",
            "instructions": f"Is the commenter genuinely unhappy with {target}?{hint}",
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
            "instructions": f"Does the comment contain this complaint about {target}? {text}{hint}",
        }
    return questions




def video_id(arg):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})", arg)
    return m.group(1) if m else arg


class YouTubeError(Exception):
    pass


def yt_get(endpoint, key, **params):
    params["key"] = key
    try:
        with urllib.request.urlopen(f"{YT_API}/{endpoint}?{urllib.parse.urlencode(params)}") as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e)["error"]["message"]
        except Exception:
            msg = str(e)
        raise YouTubeError(f"Erreur YouTube {e.code} : {msg}") from None


def fetch_video(vid, key):
    items = yt_get("videos", key, part="snippet,statistics", id=vid).get("items", [])
    if not items:
        raise YouTubeError(f"Vidéo introuvable : {vid}")
    sn, st = items[0]["snippet"], items[0].get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    return {
        "id": vid,
        "title": sn.get("title", ""),
        "channel": sn.get("channelTitle", ""),
        "published": sn.get("publishedAt", ""),
        "description": sn.get("description", ""),
        "thumbnail": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
        "views": int(st.get("viewCount", 0)),
        "likes": int(st.get("likeCount", 0)),
        "comment_count": int(st.get("commentCount", 0)),
    }


def fetch_comments(vid, key, limit):
    """Commentaires principaux, les plus pertinents d'abord.

    L'ordre « relevance » de YouTube s'arrête vers ~1 000 commentaires : au-delà, on
    complète avec l'ordre chronologique en ignorant ceux déjà récupérés.
    """
    comments, seen = [], set()
    for order in ("relevance", "time"):
        token = None
        while len(comments) < limit:
            params = {"part": "snippet", "videoId": vid, "maxResults": 100,
                      "textFormat": "plainText", "order": order}
            if token:
                params["pageToken"] = token
            data = yt_get("commentThreads", key, **params)
            for item in data.get("items", []):
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                s = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({"text": s["textDisplay"], "likes": s.get("likeCount", 0),
                                 "author": s.get("authorDisplayName", ""),
                                 "published": s.get("publishedAt", "")})
            token = data.get("nextPageToken")
            if not token:
                break
        if len(comments) >= limit:
            break
    return comments[:limit]


def score(text, key, questions, context=None, retries=5):
    state = f"{context}\n\nComment: {text[:4000]}" if context else text[:4000]
    return score_state(state, key, questions, retries)


def score_state(state, key, questions, retries=5, timeout=20):
    """Un appel Jev. Sa latence varie beaucoup (0,3 s à 15 s pour la même requête) :
    un appel qui dépasse `timeout` est relancé tout de suite, la relance répond en général vite."""
    body = json.dumps({"state": state, "model": "jev-latest", "questions": questions}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(JEV_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            answers = {k: v["noul"] for k, v in data["answers"].items()}
            return answers, data.get("usage", {})
        except urllib.error.HTTPError as e:
            if e.code in (429, 529, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                slow = isinstance(e, TimeoutError) or "timed out" in str(e)
                time.sleep(0 if slow else 2 ** attempt)
                continue
            raise


def print_progress(done, total):
    print(f"\rNotation Jev : {done}/{total}", end="" if done < total else "\n", file=sys.stderr)


def score_all(comments, key, questions, workers, on_progress=print_progress, context=None):
    usage = {"input_tokens": 0, "output_tokens": 0}
    failed = 0
    done = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futures = {ex.submit(score, c["text"], key, questions, context): c for c in comments}
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
            on_progress(done, len(comments))
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
    print(f"\n=== {vid} — mécontentement envers : {target} ===")
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
    p.add_argument("--workers", type=int, default=32, help="requêtes Jev en parallèle (défaut 32)")
    p.add_argument("--no-context", action="store_true",
                   help="ne pas donner le titre et le résumé de la vidéo à Jev")
    p.add_argument("--json", help="écrire le rapport + scores détaillés dans ce fichier")
    args = p.parse_args()

    yt_key, jev_key = os.environ.get("Youtube_V3"), os.environ.get("TYPESAFE_API_KEY")
    if not yt_key or not jev_key:
        sys.exit("Variables Youtube_V3 et TYPESAFE_API_KEY requises.")

    vid = video_id(args.video)
    try:
        meta = fetch_video(vid, yt_key)
        comments = fetch_comments(vid, yt_key, args.max)
    except YouTubeError as e:
        sys.exit(str(e))
    if not comments:
        sys.exit("Aucun commentaire trouvé (désactivés ?).")
    print(f"{len(comments)} commentaires récupérés.", file=sys.stderr)

    t0 = time.time()
    context = None if args.no_context else video_context(meta, jev_key)
    usage, failed = score_all(comments, jev_key, build_questions(args.target, context is not None),
                              args.workers, context=context)
    r = report(comments)
    print_report(vid, args.target, r, usage, failed, time.time() - t0)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"video": vid, "target": args.target, "report": r, "usage": usage, "comments": comments},
                      f, ensure_ascii=False, indent=1)
        print(f"Détails écrits dans {args.json}")


if __name__ == "__main__":
    main()
