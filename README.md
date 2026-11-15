# Peace — agent d'investissement explicable

Projet AlphaForge AI, datathon 2026 (PolyFinances, Banque Nationale, AWS).

Peace ne dit jamais « achetez » ou « vendez », et ne dit pas si une action est « bonne ». Il répond à une seule
question : **le risque de cette action correspond-il à la tolérance au risque calculée de la personne ?**
La réponse est un verdict **vert, jaune ou rouge**, avec les scores et les raisons derrière chaque chiffre.
Tout est **simulation** : aucune transaction réelle, aucun conseil financier.

## Comment il fonctionne

| Étape | Ce qui se passe | Qui décide |
| --- | --- | --- |
| Tolérance de la personne | Score de 0 à 100 calculé à partir de son historique de transactions (6 indicateurs) et de mises en situation | Code déterministe |
| Risque de l'action | Score de 0 à 100 : volatilité, baisse maximale, pires jours (CVaR), stress récent | Code déterministe |
| Actualité | Un agent lit des articles de 7 sources, ne retient que les événements qui relèvent le risque ; les points sont calculés par des règles fixes (plafond 5 points) | IA pour filtrer, code pour décider |
| Verdict | Écart entre le risque de l'action et la tolérance, puis contraintes déclarées (exclusions, horizon, concentration) : la couleur finale est la pire des deux | Code déterministe |
| Rapport | Phrases qui citent des faits numérotés ; un vérificateur en code refuse tout chiffre ou mot absent de la fiche de faits | Gabarit fixe, ou reformulation Bedrock vérifiée |

Les mêmes entrées donnent toujours le même résultat. L'IA ne calcule aucun score : elle filtre l'actualité et
reformule, et le code vérifie tout ce qu'elle produit.

## Ce qui utilise AWS

- **Amazon Bedrock** (modèle Claude Haiku, région `us-east-1`) via **Strands Agents** :
  - un agent d'actualité qui ouvre les articles avec des outils (`list_articles`, `read_article`) ; chaque événement est vérifié en code (article réellement ouvert, type dans une liste fermée, citation retrouvée mot pour mot) ;
  - un agent de questions de suivi avec trois outils en lecture seule (`get_facts`, `recompute_with_amount`, `explain_term`) ; il refuse les demandes de conseil avant tout appel au modèle.
- Les identifiants AWS ne sont **jamais** dans le dépôt : ils viennent des variables d'environnement du terminal qui lance le serveur.
- Sans identifiants, Peace fonctionne quand même : l'actualité est alors indiquée « indisponible » et le verdict ne repose que sur les prix. La page le dit.

**Application déployée sur AWS (EC2) : http://54.196.240.12/**

## Installation rapide

```bash
git clone https://github.com/apalumbo848-prog/peace-agent.git
cd peace-agent
pip install -r requirements.txt        # seulement pour les agents Bedrock ; le reste n'a besoin que de Python 3.12
python -m agent_risque.app.server      # puis ouvrir http://127.0.0.1:8765/
```

Déploiement public sur AWS (EC2) : voir [DEPLOY_AWS.md](DEPLOY_AWS.md).

## Lancer la démonstration

Python 3.12, sans autre dépendance pour le cœur du projet. Depuis le dossier `Datathon2026` :

```bash
python -m agent_risque.app.server
```

Puis ouvrir http://127.0.0.1:8765/ et choisir un profil fictif (Amira, Mateo, Robert ou Léa).

Pour activer l'actualité et les questions de suivi (Bedrock), installer `pip install strands-agents boto3` et définir
dans le terminal les variables `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` et
`AWS_DEFAULT_REGION` avant de lancer le serveur. Options : `--llm` (rapport reformulé par Bedrock), `--no-news`
(sans actualité), `--port`.

## Tests

```bash
python -m unittest discover -s agent_risque/tests -t . -v
```

213 tests : scores, verdicts, profils, répétabilité, vérificateur de texte, serveur, actualité.

## Contenu du dépôt

- `agent_risque/` : le code de Peace. Documentation détaillée dans [`agent_risque/README.md`](agent_risque/README.md), modèle de tolérance dans [`agent_risque/docs/modele_tolerance_v2.md`](agent_risque/docs/modele_tolerance_v2.md).
- `alphaforge_starter/` : les données du datathon (31 actifs, prix quotidiens du 2021-11-12 au 2026-11-12). Seul le module `data_access.py` les lit.

## Limites connues

- Les profils sont **fictifs**, avec des historiques fixes (aucun hasard).
- Le jeu de données ne contient **aucune note ESG** par entreprise : une préférence ESG est donc « pas de données » pour une action individuelle, et n'est reconnue que pour un fonds explicitement filtré ESG.
- Les barèmes et seuils marqués `[ARBITRAIRE]` dans `agent_risque/config.py` sont des choix de l'équipe, pas des vérités ; leur robustesse se vérifie avec `python -m agent_risque.analysis.sensibilite`.
- L'actualité lue est celle du jour, alors que les prix du jeu de données s'arrêtent au 2026-11-12.
- Le taux USD/CAD du jour (Banque du Canada) sert à convertir le montant affiché ; il ne modifie pas le score.
