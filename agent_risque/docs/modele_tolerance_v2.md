# Modèle de tolérance au risque v2

La **tolérance au risque** d'une personne est un score de 0 à 100 **calculé**, jamais déclaré. Il vient de deux
piliers : ce que la personne a **fait** (historique de transactions) et ce qu'elle **choisit** dans des mises en
situation fictives. Même échelle que le risque d'une action : on compare directement les deux nombres.
Tout est déterministe (aucune IA, aucun hasard) et tous les réglages sont dans `config.py`.

## 1. Vue d'ensemble

```
Historique de transactions ──► 6 indicateurs ──► score historique H (0-100)  ─┐
                                                                               ├─► tolérance = w·H + (1-w)·S
Mises en situation (3 par action) ──► score situations S (0-100) ─────────────┘     + intervalle d'incertitude
```

Le verdict compare le risque de l'action à la tolérance **moins une marge d'incertitude** (plus prudent qu'un score brut).

## 2. Pilier A : l'historique (`history_v2.py`)

On mesure ce que la personne a **supporté**, plus que ce qu'elle détient aujourd'hui.

| Indicateur | Poids | Ce qu'il mesure | Formule |
|---|---|---|---|
| Volatilité réelle du portefeuille | 25 % | À quel point la valeur du portefeuille a varié | Rendements quotidiens du portefeuille reconstitué (un achat n'est pas un gain : `r = (valeur − flux) / valeur_veille − 1`). Écart-type pondéré par la fraîcheur, ×√252, converti en points avec `VOL_ANCHORS`. |
| Pertes traversées sans vendre | 20 % | Baisses du portefeuille de 10 % ou plus gardées | Par épisode : points = `ASSET_DRAWDOWN_ANCHORS(profondeur)` si la personne n'a pas vendu (vente nette ≤ 5 %) ; sinon la moitié des points de la profondeur au moment de la vente. |
| Réaction aux baisses | 20 % | Vendre, garder ou renforcer quand un titre détenu perd 10 % | Points par événement (vente majeure 0, … renfort 100), moyenne pondérée par la fraîcheur. |
| Concentration du risque | 15 % | Le risque tient-il à très peu de titres ? | `1/HHI` sur la part de risque (valeur × volatilité) ; les FNB larges comptent pour 10 positions. |
| Part d'actifs risqués | 10 % | Part de la valeur en actifs très volatils | Moyenne de points par classe de volatilité, pondérée par la valeur. |
| Taille des positions | 10 % | Poids de la plus grosse position individuelle | `poids / 40 %`, plafonné à 100. |

**Fraîcheur** : une observation vieille de 24 mois pèse la moitié d'une d'aujourd'hui (`RECENCY_HALF_LIFE_DAYS = 730`).
Un indicateur sans donnée suffisante est **indisponible** (avec la raison) et ses poids sont redistribués : on ne suppose rien.

## 3. Pilier B : les mises en situation (`situations.py`)

À la première ouverture d'une action, trois mini-scénarios fictifs. Les **paliers sont fixes** (indépendants du titre),
pour que l'action affichée ne fausse pas la mesure.

1. **Jusqu'où iriez-vous ?** (poids 50 %) : « Seriez-vous prêt à investir X $ s'il y a un risque de perdre 10 %, 20 %, 30 %, 40 %, 50 % d'ici 2 ans ? »
   La plus grande perte acceptée est convertie en points avec **la même table que la baisse maximale d'une action**
   (`ASSET_DRAWDOWN_ANCHORS`) : tolérance et action sont dans la même unité.
2. **Après une baisse** (30 %) : la valeur baisse de 20 % six mois plus tard. Vendre tout = 0, la moitié = 33, ne rien faire = 67, racheter = 100.
3. **Deux issues possibles** (20 %) : trois paris à deux issues également probables (gain deux fois plus grand que la perte). 0 à 3 acceptés = 0 / 33 / 67 / 100 points.

Score d'une réponse = 0,5·paliers + 0,3·réaction + 0,2·paris. Score du pilier = moyenne des **12 dernières** réponses, les plus
récentes pesant plus (demi-vie de 6 réponses). Une réponse contradictoire (oui à −30 % mais non à −20 %) est comptée :
elle baisse la **cohérence**, donc la fiabilité. Le bouton « Passer » est toujours possible (la confiance baisse).

## 4. Combinaison et incertitude (`combine.py`)

- Poids de base : **60 % historique, 40 % situations** (le comportement prédit mieux que la déclaration).
- Poids réel : `w_h = 0,6·fiab_h / (0,6·fiab_h + 0,4·fiab_s)`. Un historique pauvre (peu de transactions, peu ancien, indicateurs manquants) cède du poids aux situations, et inversement.
  - `fiab_h = min(1, nb_transactions/20) × couverture × facteur d'ancienneté` ;
  - `fiab_s = min(1, nb_réponses/6) × cohérence`.
- **Confiance** = 0,45·fiab_h + 0,35·fiab_s + 0,20·accord (accord = 1 − écart/50).
- **Marge** = `15·(1 − confiance) + 0,2·max(0, |H − S| − 15)`. Le verdict utilise `tolérance − marge`. Un écart de plus de 25 points entre
  comportement et choix en scénario est affiché dans le rapport.

## 5. Pourquoi ces poids ?

Il n'existe pas de tolérance « vraie » pour optimiser statistiquement. La répartition est donc **justifiée, puis testée en robustesse** :
- le comportement observé prime sur le déclaré (60/40), mais cède la place s'il est pauvre ;
- ce que la personne a *supporté* (volatilité, pertes gardées, réaction : 65 %) pèse plus que ce qu'elle *détient* (35 %) ;
- l'analyse `python -m agent_risque.analysis.sensibilite` modifie chaque poids de ±10 points sur 124 couples (4 profils × 31 actions) :
  au plus 4 % des verdicts changent de couleur (moyenne 1,4 %), et la tolérance bouge d'au plus 2,7 points
  (voir `docs/sensibilite_v2.md`). La variation la plus influente est celle du poids de base de l'historique (60 % vers 70 %).

## 6. Limites assumées (à dire au jury)

- **Concentration et profils prudents** : sur l'historique seul, Robert (6 positions, surtout obligations et dividendes) obtient un score plus élevé
  que Mateo (FNB diversifiés) à cause des indicateurs de concentration et de taille de position, alors que sa volatilité et ses pertes sont plus faibles.
  Le score final reste dans l'ordre attendu grâce aux mises en situation.

- Les barèmes, paliers, poids, demi-vie et seuils sont des **choix d'équipe**, signalés `[ARBITRAIRE]` dans `config.py`.
- Pas de données réelles de tolérance : la validation porte sur la cohérence, la monotonie et la stabilité, pas sur une vérité terrain.
- Les mises en situation sont hypothétiques : on ne sait pas si la personne agirait ainsi. D'où le poids de 40 % et le test de cohérence.
- La concentration du risque ignore les corrélations entre titres (volatilité de chaque titre seulement).
- Simulation uniquement : aucun conseil, le verdict dit si le risque est **en accord avec la tolérance calculée**, pas si l'action est bonne.

## 7. Où est le code

| Étape | Fichier |
|---|---|
| Indicateurs de l'historique | `history_v2.py` (+ `history_score.py` pour les trois mesures reprises de la v1) |
| Mises en situation | `situations.py`, écran dans `app/pages.py`, registre dans `app/situation_ledger.py` |
| Combinaison, confiance, marge | `combine.py` (`combine_scores_v2`) |
| Verdict | `comparison.py` |
| Réglages | `config.py` (section « Modèle de tolérance v2 ») |
| Version précédente (quiz) | `SCORE_MODEL_VERSION = "v1"` dans `config.py` |
