# Sensibilité du modèle v2

Chaque ligne modifie UN réglage ; on compte les verdicts de risque qui changent de couleur sur 124 couples (3 profils fictifs x 31 actions) et le plus grand déplacement de tolérance (points sur 100).

| Variation | Verdicts changés | Déplacement max de la tolérance |
|---|---|---|
| poids de « portfolio_vol » -0.10 | 0 / 124 (0 %) | 1.6 |
| poids de « portfolio_vol » +0.10 | 2 / 124 (2 %) | 1.6 |
| poids de « loss_endured » -0.10 | 1 / 124 (1 %) | 1.6 |
| poids de « loss_endured » +0.10 | 2 / 124 (2 %) | 1.6 |
| poids de « drop_reaction » -0.10 | 3 / 124 (2 %) | 2.7 |
| poids de « drop_reaction » +0.10 | 2 / 124 (2 %) | 2.7 |
| poids de « risk_concentration » -0.10 | 2 / 124 (2 %) | 2.3 |
| poids de « risk_concentration » +0.10 | 4 / 124 (3 %) | 2.3 |
| poids de « risky_share » -0.10 | 3 / 124 (2 %) | 2.4 |
| poids de « risky_share » +0.10 | 2 / 124 (2 %) | 2.4 |
| poids de « position_size » -0.10 | 2 / 124 (2 %) | 1.5 |
| poids de « position_size » +0.10 | 0 / 124 (0 %) | 1.5 |
| poids de base historique -0.10 (60 % -> 50 %) | 3 / 124 (2 %) | 2.2 |
| poids de base historique +0.10 (60 % -> 70 %) | 5 / 124 (4 %) | 2.5 |
| situations : poids de « ladder » -0.10 | 1 / 124 (1 %) | 0.9 |
| situations : poids de « ladder » +0.10 | 1 / 124 (1 %) | 1.0 |
| situations : poids de « reaction » -0.10 | 1 / 124 (1 %) | 1.8 |
| situations : poids de « reaction » +0.10 | 1 / 124 (1 %) | 1.8 |
| situations : poids de « tradeoff » -0.10 | 3 / 124 (2 %) | 1.4 |
| situations : poids de « tradeoff » +0.10 | 1 / 124 (1 %) | 1.4 |
| demi-vie de fraîcheur 365 jours (base 730) | 0 / 124 (0 %) | 0.2 |
| demi-vie de fraîcheur 1095 jours (base 730) | 0 / 124 (0 %) | 0.1 |

Moyenne : 1.8 verdict(s) changé(s) par variation (1.4 %). Variation la plus influente : poids de base historique +0.10 (60 % -> 70 %) (5 changements).

# Comparaison v1 et v2

| Profil | Tolérance v1 | Tolérance v2 | Vert v1 / v2 | Jaune v1 / v2 | Rouge v1 / v2 |
|---|---|---|---|---|---|
| amira | 86.0 | 71.8 | 31 / 26 | 0 / 4 | 0 / 1 |
| mateo | 39.6 | 37.1 | 17 / 16 | 6 / 6 | 8 / 9 |
| robert | 22.7 | 25.7 | 4 / 4 | 10 / 11 | 17 / 16 |
| lea | 46.6 | 44.5 | 16 / 14 | 7 / 7 | 8 / 10 |
