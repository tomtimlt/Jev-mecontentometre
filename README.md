# Jev-test : % de mécontents dans les commentaires YouTube

Récupère les commentaires d'une vidéo (API YouTube Data v3), fait noter chacun par
[Jev](https://docs.typesafe.ai) (TypeSafe System One), puis agrège :

- % de commentaires mécontents (brut et pondéré par les likes), spam exclu
- raisons du mécontentement : fond, créateur/marque, pub, clickbait, technique
- les commentaires mécontents les plus likés

## Dashboard web

```bash
python3 server.py          # puis ouvrir http://127.0.0.1:8000
```

Colle une URL, choisis la cible et le nombre de commentaires : la progression s'affiche en
direct, puis le dashboard montre le % de mécontents (brut et pondéré par likes), les raisons,
la distribution des scores, et la liste filtrable des commentaires. Le seuil de décision est
réglable en direct. Les clés restent côté serveur ; chaque analyse est enregistrée dans `runs/`.

## Ligne de commande

```bash
export Youtube_V3=...        # clé YouTube Data v3
export TYPESAFE_API_KEY=...  # clé Jev
python3 jev_comments.py "https://www.youtube.com/watch?v=BGY647T1FKo" --target "Apple" --max 300
```

Options : `--target` (contre qui mesurer le mécontentement, défaut : la vidéo ou son créateur),
`--max` (nombre de commentaires, défaut 500), `--workers` (parallélisme Jev), `--json` (export détaillé).

Aucune dépendance : Python 3 standard uniquement.
