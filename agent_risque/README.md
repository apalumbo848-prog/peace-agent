# Peace : agent d'investissement explicable (AlphaForge AI)

# agent_risque : étape 1, score de tolérance au risque

Calcule un score de 0 à 100 (0 = prudent, 100 = tolérant au risque) à partir
d'un historique de transactions fictif (50 %) et d'un quiz de 5 mises en
situation (50 %). Aucun modèle d'IA, aucun hasard : mêmes entrées = même score.

## Modules

| Fichier | Rôle |
| --- | --- |
| `config.py` | Tous les poids, seuils, barèmes et le quiz, chacun justifié |
| `data_access.py` | Seul module qui lit les CSV (à remplacer pour des sources en ligne) |
| `metrics.py` | Volatilité annualisée et barème commun volatilité -> points |
| `transactions.py` | Transactions et validation (aucune donnée inventée) |
| `history_score.py` | 5 indicateurs de l'historique, avec contributions |
| `quiz.py` | Quiz à barème fixe |
| `combine.py` | Score final, indice de confiance, profil complet |
| `profile_store.py` | Sauvegarde JSON du profil et de son détail de calcul |
| `asset_score.py` | Étape 2 : `score_asset(ticker, as_of)`, score de risque d'une action (0-100) |
| `comparison.py` | Étape 3 : `compare(profil, action, montant)`, verdict vert/jaune/rouge et facteurs |
| `constraints.py` | Étape 3 : exclusions, horizon, concentration, préférences (règles fixes) |
| `fixtures/personas.py` | 4 profils fictifs (Amira, Mateo, Robert, Léa) lus dans `fixtures/profiles/*.json` ; régénérés par `fixtures/build_profiles.py` |

## Utilisation

```python
from datetime import date
from agent_risque import combine, profile_store, quiz
from agent_risque.fixtures import personas

args = personas.all_personas()["equilibre"]
profile = combine.compute_user_profile(**args)
print(profile["final_score_display"], profile["confidence"]["label"])
profile_store.save_profile(profile, "profils")
```

Score d'une action (appelé seulement à l'ouverture de sa page) :

```python
from agent_risque.asset_score import score_asset
result = score_asset("SPY", date(2026, 11, 12))
print(result.score_display, result.confidence["label"], result.warnings)
```

Verdict sur la page d'achat (profil + action, montant facultatif en CAD) :

```python
from agent_risque import comparison
verdict = comparison.compare(profile, result, planned_amount_cad=2000)
print(verdict["final_color"], verdict["summary_fr"])
```

Les champs déclarés (`declared`) suivent ce format : `{"horizon_years": [3, 5],
"exclusions": {"asset_classes": [], "sectors": [], "tickers": []}, "preferences": []}`.

Rapport explicatif (étape 4), page HTML autonome (CSS et SVG intégrés, sans JavaScript) :

```python
from agent_risque.report import render_html
html, info = render_html.make_report_page(profile, "QQQ", planned_amount_cad=2000)   # mode="template" par défaut
render_html.write_report("rapport_QQQ.html", html)
```

- Le niveau de détail (`debutant`, `intermediaire`, `avance`) suit le champ déclaré `experience`, ou l'argument `level=`.
- Chaque phrase cite des faits numérotés (F1, F2…) ; un vérificateur en code refuse tout nombre, date, sigle ou
  expression incitative absent de la fiche de faits.
- `mode="template"` : texte fixe, aucun appel externe, résultat identique à chaque exécution.
- `mode="llm"` : reformulation par Amazon Bedrock (`config.REPORT_MODEL_ID`). Il faut `boto3` et des identifiants AWS
  dans l'environnement. Le modèle ne reçoit que la fiche de faits (profils fictifs). Sa sortie n'est gardée que si le
  vérificateur l'accepte (2 essais), sinon retour au texte fixe ; le résultat accepté est mis en cache.
  Le raisonnement interne du modèle n'est ni lu ni conservé.
- Dossiers `report/` : `facts.py` (faits), `template_text.py`, `llm_text.py`, `verify.py`, `charts.py`, `trace.py`, `render_html.py`.

Page de démonstration et agent de suivi (étape 5) :

```bash
python -m agent_risque.app.server          # puis ouvrir http://127.0.0.1:8765/
python -m agent_risque.app.server --llm    # rapport reformulé par Bedrock (identifiants AWS requis)
```

- `app/server.py` : serveur local (bibliothèque standard), 127.0.0.1 seulement, Host et Origin contrôlés, aucun JavaScript.
  Le calcul démarre à l'ouverture de la page d'une action.
- `app/ledger.py` : registre des achats SIMULÉS (JSON dans `app_data/`) ; chaque achat devient une transaction ordinaire,
  le profil est recalculé de zéro avec les mêmes règles. Sur la page d'une action : pastille du verdict (icône différente par couleur), puis « Simuler un achat »
  (sans case à cocher), puis « En savoir plus » qui déplie les scores, la comparaison des tolérances, « Pourquoi ? » et la trace.
- `agent/tools.py` : 3 outils en lecture seule (`get_facts`, `recompute_with_amount`, `explain_term`) et réponses préparées sans IA.
- `agent/followup.py` : agent Strands (`Agent` + `BedrockModel` + `@tool`) pour la question libre. Refus fixe des demandes de conseil
  (avant tout appel au modèle) ; réponse affichée seulement si `verify.check_sentence` l'accepte, sinon message de repli.
- Dépendances de l'étape 5 : `pip install strands-agents` (le reste du projet n'en a pas besoin).

Actualité et taux du jour (`news/`, `fx_live.py`), activés par défaut (`--no-news` pour les couper) :

- `news/feeds.py` lit les flux RSS de 7 sources (gauche : The Guardian, IRIS ; neutre : BBC News, CNBC, Yahoo Finance ; droite :
  Fox Business, Contrepoints), garde les articles qui parlent de l'action et récupère le texte intégral. Reuters n'a pas de flux public.
  Les étiquettes sont une orientation éditoriale généralement attribuée, pas une mesure.
- `news/agent.py` : agent Strands + Bedrock qui ouvre les articles (outils `list_articles`, `read_article`) et déclare les événements qui
  relèvent le risque. Chaque événement est vérifié en code (article ouvert, type dans une liste fermée, citation retrouvée mot pour mot).
- `news/impact.py` : règles fixes. Un événement compte s'il est confirmé par 2 sources ; gravité retenue = la plus basse ; règle du nombre : 3 articles
  défavorables distincts non confirmés = +1 point, 5 ou plus = +2 ; total plafonné à 5 points ; si les sources divergent, la marge d'incertitude du verdict s'élargit de 3 points. Seuls les événements qui relèvent le risque comptent.
- Le résultat est enregistré par action et par jour (`app_data/news/`) : même page, même verdict, jusqu'à « Actualiser ».
- `fx_live.py` : taux USD/CAD du jour (Banque du Canada), affiché et utilisé pour convertir un montant ; il ne change pas le score.
- Il faut des identifiants AWS dans l'environnement du terminal qui lance le serveur ; sans eux, l'actualité est « indisponible »
  et le verdict ne repose que sur les prix (la page le dit).

Modèle de tolérance v2 (défaut) : historique à 6 indicateurs + mises en situation à la place du quiz.
Explication complète, formules et limites : [docs/modele_tolerance_v2.md](docs/modele_tolerance_v2.md).
`SCORE_MODEL_VERSION = "v1"` dans `config.py` rétablit le quiz de la première version. La robustesse des poids se vérifie avec
`python -m agent_risque.analysis.sensibilite` (résultat dans `docs/sensibilite_v2.md`).

Lancer depuis le dossier parent de `agent_risque` (Datathon2026).

## Tests

```bash
python -m unittest discover -s agent_risque/tests -t . -v
```

Dépendances : bibliothèque standard de Python 3.12 seulement. Les données
attendues sont dans `../alphaforge_starter` (voir `config.DATA_DIR`).

## Limites connues (étape 1)

- Les valeurs de `config.py` marquées [ARBITRAIRE] sont des hypothèses, pas des vérités.
- Un FNB large compte comme 10 positions : sa composition n'est pas dans les données.
- La volatilité est mesurée dans la devise de cotation (effet du change non inclus).
- Les champs déclarés (horizon, préférences) sont conservés mais pas encore notés.
- Aucune actualité ni donnée ESG dans le jeu de départ : rien de tel n'est utilisé.
