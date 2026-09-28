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

## Structure de la requête Jev

Chaque commentaire est envoyé avec le contexte de la vidéo (titre, chaîne, premier paragraphe
de la description) dans le `state`, et les questions demandent de juger uniquement le commentaire :

```
state: YouTube video "<titre>" by <chaîne>.
       Video summary: <résumé>

       Comment: <commentaire>
```

`eval/compare_prompts.py` compare plusieurs structures sur un jeu étiqueté à la main
(`eval/apple_ipad_crush.json`, 38 commentaires surtout ambigus) :

| Variante | Exactitude | AUC |
|---|---|---|
| Commentaire seul | 79 % | 0,90 |
| + titre | 87 % | 0,98 |
| **+ titre + résumé (retenu)** | **95-97 %** | **0,98** |
| Résumé dans les instructions | 84-89 % | 0,95 |

`--no-context` désactive le contexte en ligne de commande.

## Déploiement gratuit (Render)

1. Sur [render.com](https://render.com), **New → Blueprint** et choisir ce repo (branche avec `render.yaml`).
2. Renseigner les variables demandées : `TYPESAFE_API_KEY`, `Youtube_V3` et **`APP_PASSWORD`**
   (obligatoire en public, sinon n'importe qui consomme tes quotas).
3. Ouvrir l'URL `https://<nom>.onrender.com` : le navigateur demande un identifiant
   (n'importe lequel) et le mot de passe.

Offre gratuite : le service s'endort après 15 min sans visite (environ 1 min pour se réveiller)
et le disque n'est pas persistant, donc l'historique `runs/` est perdu à chaque redémarrage.
