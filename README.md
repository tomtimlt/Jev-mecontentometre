# Jev-test : % de mécontents dans les commentaires YouTube

Récupère les commentaires d'une vidéo (API YouTube Data v3), fait noter chacun par
[Jev](https://docs.typesafe.ai) (TypeSafe System One), puis agrège :

- % de commentaires mécontents (brut et pondéré par les likes), spam exclu
- raisons du mécontentement : fond, créateur/marque, pub, clickbait, technique
- les commentaires mécontents les plus likés

## Usage

```bash
export Youtube_V3=...        # clé YouTube Data v3
export TYPESAFE_API_KEY=...  # clé Jev
python3 jev_comments.py "https://www.youtube.com/watch?v=BGY647T1FKo" --target "Apple" --max 300
```

Options : `--target` (contre qui mesurer le mécontentement, défaut : la vidéo ou son créateur),
`--max` (nombre de commentaires, défaut 500), `--workers` (parallélisme Jev), `--json` (export détaillé).

Aucune dépendance : Python 3 standard uniquement.
