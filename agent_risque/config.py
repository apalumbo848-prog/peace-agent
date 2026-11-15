"""Configuration unique de l'étape 1 : score de tolérance au risque de l'utilisateur.

Tous les poids, seuils et barèmes du projet vivent ICI, chacun avec sa justification.
Aucun autre module ne contient de constante de calcul.

Convention : tous les scores vont de 0 (prudent) à 100 (tolérant au risque).
Les choix marqués [ARBITRAIRE] sont des hypothèses documentées, pas des vérités :
ils doivent être présentés comme tels dans la documentation technique.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONFIG_VERSION = "1.0"

# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------

# Dossier du jeu de départ (CSV fournis par le datathon). Utilisé uniquement
# par data_access.py, pour qu'on puisse remplacer la source sans toucher au reste.
DATA_DIR = Path(__file__).resolve().parent.parent / "alphaforge_starter"

# --------------------------------------------------------------------------
# Volatilité (mesure reconnue : écart-type annualisé des rendements logarithmiques)
# --------------------------------------------------------------------------

# Jours d'annualisation : 252 séances pour les actions/FNB ; 365 pour les cryptos,
# qui se négocient 7 jours sur 7 (le README du jeu de données le précise).
ANNUALIZATION_DAYS = {"default": 252, "crypto": 365}

# Fenêtre de volatilité : 365 jours calendaires AVANT la transaction, afin de ne
# jamais utiliser une information qui n'existait pas encore (cohérence temporelle).
VOL_WINDOW_DAYS = 365

# Nombre minimal de rendements pour accepter une volatilité. En dessous, on
# signale l'absence de donnée au lieu de la supposer. [ARBITRAIRE]
VOL_MIN_OBS = 120

# Barème volatilité annualisée (%) -> points 0-100, interpolé linéairement.
# Ancrages tirés de l'univers 2021-2026 (adj_close) : ZST.TO 0,6 % ; AGG 6,2 % ;
# SPY 17,3 % ; AAPL 28,1 % ; BTC 50,8 % ; NVDA 51,6 % ; ETH 68,4 %.
# Le même barème servira à l'étape 2 pour le risque des actions, afin que le
# score utilisateur et le score d'action soient sur une échelle commune.
# [ARBITRAIRE] : les points attribués à chaque ancrage.
VOL_ANCHORS = ((0.0, 0.0), (6.0, 10.0), (17.0, 35.0), (30.0, 65.0), (50.0, 90.0), (70.0, 100.0))

# --------------------------------------------------------------------------
# Indicateurs de l'historique
# --------------------------------------------------------------------------

# Poids des cinq indicateurs (somme = 1). I1 et I4 mesurent le risque choisi,
# I3 le comportement réel sous stress ; I2 et I5 sont plus structurels (une
# position concentrée peut refléter un manque de connaissance autant qu'une
# tolérance). [ARBITRAIRE]
INDICATOR_WEIGHTS = {
    "volatility": 0.30,
    "concentration": 0.15,
    "drop_reaction": 0.25,
    "risky_share": 0.20,
    "position_size": 0.10,
}

# I2 - concentration : nombre effectif de positions = 1 / HHI (indice de
# Herfindahl-Hirschman). Un FNB large compte comme 10 positions car on ne dispose
# pas de sa composition (pas de transparence). [ARBITRAIRE]
DIVERSIFIED_ETF_CLASSES = ("etf_equity", "etf_bond")
ETF_DIVERSIFICATION_FACTOR = 10
# Au moins 10 positions effectives = portefeuille pleinement diversifié (score 0). [ARBITRAIRE]
N_EFF_TARGET = 10

# I3 - réaction aux baisses.
DROP_THRESHOLD = 0.10            # baisse d'au moins 10 % sous le plus haut récent (énoncé)
DROP_PEAK_LOOKBACK_ROWS = 60     # plus haut des 60 séances précédentes [ARBITRAIRE]
DROP_COOLDOWN_ROWS = 60          # délai avant de compter un nouvel événement sur le même titre [ARBITRAIRE]
DROP_REACTION_WINDOW_ROWS = 20   # réaction observée sur 20 séances (~1 mois) [ARBITRAIRE]
# Variation nette de la position pendant la fenêtre -> points. Première règle vraie gagne.
# (opérateur, seuil, points) ; sinon DROP_REACTION_DEFAULT_POINTS (vente majeure).
# Inspirations : effet de disposition (Shefrin et Statman, 1985), aversion aux
# pertes (Kahneman et Tversky, 1979). [ARBITRAIRE] : seuils et points.
DROP_REACTION_RULES = ((">=", 0.10, 100.0), (">", -0.10, 65.0), (">", -0.50, 30.0))
DROP_REACTION_DEFAULT_POINTS = 0.0

# I4 - part d'actifs risqués : seaux selon la volatilité des 365 jours avant as_of.
# Vide naturel observé entre obligations (<= 6,6 %) et actions (>= 13,1 %) -> 12 % ;
# 25 % sépare les grandes capitalisations stables (<= 24,4 %, JPM) des titres plus
# volatils (XOM 26,7 % et plus).
RISK_BUCKET_LOW_MAX = 12.0
RISK_BUCKET_HIGH_MIN = 25.0
RISK_BUCKET_POINTS = {"low": 0.0, "medium": 50.0, "high": 100.0}

# I5 - taille des positions : poids de la plus grosse position individuelle
# (actions et cryptos, FNB exclus). 40 % ou plus = score 100. [ARBITRAIRE]
SINGLE_NAME_CLASSES = ("equity", "crypto")
SINGLE_NAME_MAX_WEIGHT = 0.40

# Un prix de valorisation plus vieux que ce nombre de jours déclenche un avertissement.
STALE_PRICE_DAYS = 10

# --------------------------------------------------------------------------
# Quiz : 5 mises en situation, 4 réponses chacune, points 0 / 33 / 67 / 100.
# Les points sont fixes ; le score du quiz est la moyenne des points.
# Inspiration : échelle de tolérance au risque de Grable et Lytton (1999)
# (référence à vérifier avant citation dans la documentation).
# [ARBITRAIRE] : textes, réponses et points.
# --------------------------------------------------------------------------

QUIZ_QUESTIONS = (
    {
        "id": "q1_chute",
        "text": "Votre portefeuille de 10 000 $ perd 20 % en un mois. Que faites-vous ?",
        "answers": (
            ("Je vends tout pour limiter les dégâts.", 0),
            ("Je vends une partie pour réduire mon risque.", 33),
            ("Je ne fais rien et j'attends.", 67),
            ("J'en rachète : les prix sont plus bas.", 100),
        ),
    },
    {
        "id": "q2_gain_perte",
        "text": "Quatre placements fictifs sur un an. Lequel choisissez-vous ?",
        "answers": (
            ("Placement A : gain possible de 3 %, perte possible de 0 %.", 0),
            ("Placement B : gain possible de 8 %, perte possible de 8 %.", 33),
            ("Placement C : gain possible de 15 %, perte possible de 20 %.", 67),
            ("Placement D : gain possible de 30 %, perte possible de 40 %.", 100),
        ),
    },
    {
        "id": "q3_titre_mediatise",
        "text": "Un titre très médiatisé a pris 40 % en un mois. Que faites-vous ?",
        "answers": (
            ("Rien : je n'investis pas dans ce genre de titre.", 0),
            ("J'y mets 1 % de mon capital.", 33),
            ("J'y mets 10 % de mon capital.", 67),
            ("J'y mets 25 % de mon capital.", 100),
        ),
    },
    {
        "id": "q4_part_volatile",
        "text": "Quelle part de votre capital êtes-vous à l'aise de placer dans des actifs très volatils (cryptos, croissance) ?",
        "answers": (
            ("0 %.", 0),
            ("Environ 10 %.", 33),
            ("Environ 30 %.", 67),
            ("Environ 60 %.", 100),
        ),
    },
    {
        "id": "q5_regret",
        "text": "Qu'est-ce qui vous dérangerait le plus ?",
        "answers": (
            ("Perdre 15 % sur un placement risqué.", 0),
            ("Perdre 15 %, mais seulement si je pouvais récupérer d'ici quelques années.", 33),
            ("Manquer un gain de 15 % à cause d'un excès de prudence, sans que cela m'empêche de dormir.", 67),
            ("Manquer un gain de 15 % : je préfère prendre le risque.", 100),
        ),
    },
)

# --------------------------------------------------------------------------
# Combinaison historique / quiz et confiance
# --------------------------------------------------------------------------

# Poids de l'historique quand il est pleinement fiable (énoncé : 50 % / 50 %).
HISTORY_WEIGHT_BASE = 0.5
# Nombre de transactions valides à partir duquel l'historique est jugé suffisant.
# En dessous, son poids baisse linéairement et le quiz pèse davantage. [ARBITRAIRE]
N_TRANSACTIONS_FULL = 20

# Indice de confiance 0-1 = somme pondérée de trois éléments. [ARBITRAIRE]
CONFIDENCE_WEIGHTS = {"quiz_completeness": 0.35, "history_reliability": 0.45, "agreement": 0.20}
# Écart historique/quiz (en points) à partir duquel l'accord est nul.
AGREEMENT_GAP_MAX = 50.0
# Écart à partir duquel on signale à l'utilisateur que son comportement et ses
# réponses divergent. [ARBITRAIRE]
DIVERGENCE_WARNING_GAP = 25.0
# Seuils d'étiquette relevés à l'étape 3 (0,4 / 0,7 rendaient tout « élevé »). [ARBITRAIRE]
CONFIDENCE_LABEL_LOW_MAX = 0.6
CONFIDENCE_LABEL_MEDIUM_MAX = 0.9

# --------------------------------------------------------------------------
# Étape 2 : score de risque d'une action (0 = très stable, 100 = très risqué)
# --------------------------------------------------------------------------

# Fenêtre d'analyse : jusqu'à 5 ans avant as_of (les données commencent le
# 2021-11-12). Elle inclut 2022, quand actions et obligations ont reculé ensemble.
ASSET_WINDOW_DAYS = 1826
# Sous ce nombre de rendements (~1 an), aucun score n'est produit. [ARBITRAIRE]
ASSET_MIN_RETURNS = 250
# Nombre de rendements jugé suffisant (~5 ans de séances) pour la confiance. [ARBITRAIRE]
ASSET_FULL_RETURNS = 1250

# S1 - volatilité = mélange de la volatilité sur la fenêtre et des 365 derniers jours
# (capte un changement de régime : GLD 19,3 % sur 5 ans contre 29,2 % sur 1 an).
# Barème = VOL_ANCHORS, identique à celui de l'utilisateur (échelle commune). [ARBITRAIRE] : 50/50.
ASSET_VOL_RECENT_SHARE = 0.5

# S2 - baisse maximale sur la fenêtre (drawdown maximal ; Magdon-Ismail et Atiya, 2004),
# |baisse| en % -> points. Complète la volatilité : TLT a 15,6 % de volatilité
# mais a perdu 43,7 % au pire. Points alignés sur ceux de la volatilité. [ARBITRAIRE]
ASSET_DRAWDOWN_ANCHORS = ((0.0, 0.0), (5.0, 10.0), (20.0, 35.0), (35.0, 65.0), (55.0, 90.0), (80.0, 100.0))

# S3 - risque de queue : CVaR 95 % historique (Rockafellar et Uryasev, 2000), soit la perte
# moyenne des 5 % de jours les plus mauvais, en % par jour -> points. [ARBITRAIRE]
ASSET_TAIL_QUANTILE = 0.05
ASSET_TAIL_ANCHORS = ((0.0, 0.0), (0.5, 10.0), (2.5, 35.0), (4.5, 65.0), (7.0, 90.0), (10.0, 100.0))

# S4 - stress récent : écart actuel sous le plus haut des 252 dernières séances
# (descriptif du moment, poids faible : une forte baisse peut aussi être une occasion). [ARBITRAIRE]
ASSET_STRESS_LOOKBACK_ROWS = 252
ASSET_STRESS_ANCHORS = ((0.0, 0.0), (5.0, 15.0), (15.0, 45.0), (30.0, 80.0), (50.0, 100.0))

# Poids de base (somme = 1). S5 « actualité » est réservée : aucune actualité dans le
# jeu de données, elle est donc indisponible et son poids est redistribué (0,35 / 0,30 /
# 0,25 / 0,10 sur les quatre autres) mais réduit la couverture, donc la confiance. [ARBITRAIRE]
ASSET_COMPONENT_WEIGHTS = {
    "volatility": 0.28,
    "drawdown": 0.24,
    "tail_risk": 0.20,
    "recent_stress": 0.08,
    "news": 0.20,
}

# Confiance du score d'action (0-1). [ARBITRAIRE]
ASSET_CONFIDENCE_WEIGHTS = {"data_sufficiency": 0.5, "coverage": 0.3, "stability": 0.2}
# Plancher du dénominateur de la stabilité (évite de grossir l'écart relatif des actifs peu volatils).
ASSET_STABILITY_VOL_FLOOR = 5.0
# Écart relatif entre volatilité récente et volatilité de la fenêtre qui déclenche un avertissement.
ASSET_REGIME_SHIFT_WARNING = 0.30

# Anomalies connues des données (sources : README du jeu de départ). Affichées en avertissement.
KNOWN_DATA_ISSUES = {
    "CNQ.TO": ("Le 'fractionnement' de 1,021 du 2022-08-22 coïncide avec un dividende de 0,75 $ : "
               "il s'agit probablement d'une distribution spéciale, à vérifier auprès de CNQ."),
}

# Mentions rappelées dans chaque résultat (encadrement responsable du défi).
ASSET_DISCLAIMERS = (
    "Les performances passées ne garantissent pas les résultats futurs.",
    "Score de risque historique, pas un conseil financier.",
    "Simulation : aucune transaction réelle.",
)

# Tant que l'actualité manque, l'étiquette de confiance d'une action ne dépasse pas ce niveau.
ASSET_LABEL_CAP_WITHOUT_NEWS = "moyenne"

# --------------------------------------------------------------------------
# Étape 3 : comparaison profil / action et contraintes
# --------------------------------------------------------------------------

# Marge d'incertitude : tolérance effective = score utilisateur - marge, avec
# marge = VERDICT_MAX_UNCERTAINTY_MARGIN * (1 - confiance du profil). L'incertitude
# ne rend donc jamais un verdict plus vert. [ARBITRAIRE]
VERDICT_MAX_UNCERTAINTY_MARGIN = 15.0

# Écart = score de l'action - tolérance effective (en points).
# Vert si écart <= 10 ; jaune si <= 25 ; rouge au-delà. Repère : une réponse du quiz
# vaut 33 points, donc 10 points ~ 1/3 de cran et 25 points ~ 3/4 de cran. [ARBITRAIRE]
VERDICT_GREEN_MAX_GAP = 10.0
VERDICT_YELLOW_MAX_GAP = 25.0
# Écart <= -30 : action bien plus prudente que la tolérance (couleur inchangée, message ajouté).
VERDICT_TOO_SAFE_GAP = -30.0

# Contraintes (constraints.py). Violation = rouge, attention = jaune. [ARBITRAIRE]
CONSTRAINT_SHORT_HORIZON_YEARS = 5          # horizon maximal déclaré <= 5 ans = horizon court
CONSTRAINT_HIGH_RISK_ASSET_SCORE = 60.0     # score d'action à partir duquel l'horizon court alerte
CONSTRAINT_SINGLE_NAME_ATTENTION = 0.25     # poids d'un titre après achat : attention au-delà
# Violation du poids d'un titre : SINGLE_NAME_MAX_WEIGHT (0,40, étape 1).
CONSTRAINT_SECTOR_ATTENTION = 0.50          # poids d'un secteur (hors FNB larges) : attention au-delà

# Phrases d'ouverture fixes (repli déterministe pour le futur rapport). Aucun verbe d'incitation
# (« achetez », « vendez ») : le verdict décrit une adéquation, pas un conseil.
VERDICT_HEADLINES = {
    "vert": "Cette action correspond à votre tolérance au risque (écart de {gap:+.0f} {unit}).",
    "jaune": "Cette action est un peu plus risquée que votre tolérance (écart de {gap:+.0f} {unit}).",
    "rouge": "Cette action est nettement plus risquée que votre tolérance (écart de {gap:+.0f} {unit}).",
}
VERDICT_TOO_SAFE_MESSAGE = ("Cette action est bien plus prudente que votre tolérance : "
                            "elle ne met pas à profit le niveau de risque que vous acceptez.")

# --------------------------------------------------------------------------
# Étape 4 : rapport explicatif (texte fixe ou reformulation par un modèle) et graphiques
# --------------------------------------------------------------------------

# Niveaux de détail (champ déclaré 'experience') ; défaut = intermédiaire. [ARBITRAIRE]
REPORT_LEVELS = ("debutant", "intermediaire", "avance")
REPORT_DEFAULT_LEVEL = "intermediaire"

# Sections obligatoires, dans l'ordre d'affichage.
REPORT_SECTION_TITLES = (
    ("en_bref", "En bref"),
    ("pourquoi", "Pourquoi ce résultat"),
    ("profil", "Votre profil"),
    ("action", "L'action"),
    ("contraintes", "Vos contraintes"),
    ("limites", "Ce qu'il faut savoir"),
)
# Nombre maximal de phrases par section et par niveau (les faits obligatoires passent toujours).
REPORT_MAX_SENTENCES = {
    "debutant": {"en_bref": 3, "pourquoi": 2, "profil": 2, "action": 3, "contraintes": 2, "limites": 3},
    "intermediaire": {"en_bref": 4, "pourquoi": 3, "profil": 3, "action": 4, "contraintes": 2, "limites": 4},
    "avance": {"en_bref": 5, "pourquoi": 6, "profil": 5, "action": 7, "contraintes": 5, "limites": 6},
}
# Plafonds de longueur du texte principal (mots) et de chaque phrase. [ARBITRAIRE]
REPORT_MAX_WORDS = {"debutant": 230, "intermediaire": 370, "avance": 560}
REPORT_MAX_SENTENCE_WORDS = 32

# Expressions interdites (minuscules) : le rapport décrit une adéquation, il ne donne pas de conseil.
REPORT_BANNED_PHRASES = (
    "achetez", "vendez", "acheter maintenant", "vendre maintenant", "nous recommandons",
    "je recommande", "vous devriez", "vous devez acheter", "il faut acheter", "il faut vendre",
    "sans risque", "garanti", "rendement assuré", "ne ratez pas",
    # jugement de valeur : l'outil dit « en accord ou non avec votre profil », jamais « bon » ou « mauvais »
    "bonne action", "mauvaise action", "bon investissement", "mauvais investissement", "bon choix", "mauvais choix",
    "à éviter", "à privilégier", "vaut la peine",
)
# Sigles que le texte peut employer même s'ils ne sont pas dans les faits.
REPORT_ALLOWED_TERMS = ("CAD", "USD", "ESG", "FNB", "IA")

# Reformulation par modèle (facultative, jamais utilisée pour calculer un score).
# Le paramètre 'temperature' est déprécié sur ces modèles : on met le résultat en cache.
REPORT_MODEL_ID = "us.anthropic.claude-haiku-5-5"      # option : "us.anthropic.claude-sonnet-5-5"
REPORT_REGION = "us-east-1"
REPORT_MAX_TOKENS = 12000    # large : le modèle dépense une partie du budget en raisonnement interne (ignoré, jamais lu)
REPORT_MAX_ATTEMPTS = 2          # un essai + un nouvel essai avec la liste des erreurs, puis texte fixe
REPORT_PROMPT_VERSION = "1"
REPORT_CACHE_DIR = Path(__file__).resolve().parent / "report_cache"

# Hypothèses affichées dans le rapport (choix de l'équipe, pas des vérités).
REPORT_ASSUMPTIONS_FR = (
    "Les barèmes qui transforment la volatilité, la baisse maximale et les pires jours en points "
    "sont des choix de l'équipe.",
    "Le score de risque décrit le passé observé sur la période indiquée ; il ne prédit pas l'avenir.",
)

# ---------------------------------------------------------------------------
# Modèle de tolérance v2 : historique à 6 indicateurs + mises en situation (remplacent le quiz)
# ---------------------------------------------------------------------------
# "v1" = quiz de 5 questions et historique à 5 indicateurs (conservé pour comparer) ; "v2" = modèle ci-dessous.
SCORE_MODEL_VERSION = "v2"

# Poids des 6 indicateurs de l'historique v2 (somme = 1). [ARBITRAIRE, justifié dans le README]
# Ce que la personne a SUPPORTÉ (volatilité réelle, pertes gardées, réaction) pèse plus que ce qu'elle DÉTIENT
# aujourd'hui (concentration du risque, part risquée, taille d'une position).
HISTORY_V2_WEIGHTS = {
    "portfolio_vol": 0.25,        # volatilité réelle du portefeuille, reconstituée jour par jour
    "loss_endured": 0.20,         # pertes du portefeuille traversées sans vendre
    "drop_reaction": 0.20,        # réaction aux baisses de 10 % d'un titre détenu (comme v1, avec fraîcheur)
    "risk_concentration": 0.15,   # concentration du RISQUE (valeur x volatilité), pas de la valeur
    "risky_share": 0.10,
    "position_size": 0.10,
}
RECENCY_HALF_LIFE_DAYS = 730         # une observation de 24 mois pèse la moitié d'une d'aujourd'hui [ARBITRAIRE]
PORTFOLIO_VOL_MIN_DAYS = 60          # moins de 60 rendements de portefeuille : indicateur indisponible
LOSS_EPISODE_MIN_DEPTH = 0.10        # une baisse du portefeuille compte à partir de -10 % sous son plus haut
LOSS_SELL_TOLERANCE = 0.05           # vente nette <= 5 % de la valeur pendant l'épisode = « sans vendre »
LOSS_SALE_FACTOR = 0.5               # une vente à la profondeur D révèle une limite d'environ D, réduite de moitié [ARBITRAIRE]
HISTORY_SPAN_FULL_DAYS = 365         # l'historique est pleinement fiable à partir d'un an d'ancienneté
HISTORY_SPAN_MIN_FACTOR = 0.5        # fiabilité minimale d'un historique très court (multiplicateur)

# Mises en situation : trois mini-scénarios fictifs, posés à la première ouverture d'une action.
# Les paliers sont FIXES (indépendants de l'action) pour que la mesure ne soit pas influencée par le titre affiché.
SITUATION_HORIZON_YEARS = 2
SITUATION_LADDER_LEVELS = (10, 30, 50)      # pertes possibles proposées (%), d'ici l'horizon
SITUATION_LADDER_ANCHORS = ASSET_DRAWDOWN_ANCHORS    # même table que la baisse maximale de l'action : même unité
SITUATION_REACTION_DROP_PCT = 20
SITUATION_REACTION_MONTHS = 6
SITUATION_REACTION_OPTIONS = (                       # (texte, points)
    ("Je vends tout", 0.0),
    ("Je vends la moitié", 33.0),
    ("Je ne fais rien", 67.0),
    ("J'en rachète davantage", 100.0),
)
SITUATION_TRADEOFFS = ((20, 10), (40, 20), (60, 30))  # (gain %, perte %), deux issues également probables, rapport 2 pour 1
SITUATION_TRADEOFF_POINTS = (0.0, 33.0, 67.0, 100.0)  # selon le nombre d'issues acceptées (0 à 3)
SITUATION_PART_WEIGHTS = {"ladder": 0.5, "reaction": 0.3, "tradeoff": 0.2}
SITUATION_N_FULL = 6                  # nombre de réponses pour une fiabilité complète
SITUATION_MAX_KEPT = 12               # seules les 12 dernières réponses comptent
SITUATION_RECENCY_HALF_LIFE = 6       # une réponse 6 positions plus ancienne pèse la moitié
SITUATION_INCONSISTENCY_PENALTY = 0.5 # part de fiabilité perdue si TOUTES les réponses sont incohérentes
SITUATION_SPREAD_FULL = 40.0          # écart-type (points) entre réponses à partir duquel la cohérence perd l'autre moitié

# Combinaison v2 : l'historique prime (le comportement prédit mieux que la déclaration) mais cède du poids s'il est pauvre.
HISTORY_WEIGHT_BASE_V2 = 0.60
CONFIDENCE_WEIGHTS_V2 = {"situations": 0.35, "history": 0.45, "agreement": 0.20}
# Marge d'incertitude sur la tolérance : 15 x (1 - confiance) + coefficient x (écart historique/situations au-delà du seuil).
TOLERANCE_MARGIN_GAP_FREE = 15.0
TOLERANCE_MARGIN_GAP_COEF = 0.2


# ---------------------------------------------------------------------------
# Étape 5 : page de démonstration, registre d'achats simulés, questions de suivi
# ---------------------------------------------------------------------------
APP_DATA_DIR = Path(__file__).resolve().parent / "app_data"   # registres JSON des achats simulés
APP_HOST = "127.0.0.1"                    # écoute locale seulement
APP_PORT = 8765
APP_DEFAULT_AMOUNT_CAD = 2000.0           # [ARBITRAIRE] montant proposé par défaut
APP_MAX_AMOUNT_CAD = 5_000_000.0          # plafond de saisie (refuse les montants absurdes)
LEDGER_MAX_ENTRIES = 200                  # plafond d'achats simulés par profil

FOLLOWUP_MAX_QUESTION_CHARS = 300         # [ARBITRAIRE] longueur maximale d'une question libre
FOLLOWUP_MAX_QUESTIONS_PER_PAGE = 5       # [ARBITRAIRE] questions libres par profil et par action
FOLLOWUP_MAX_ATTEMPTS = 2                 # un essai + un nouvel essai avec les erreurs, puis repli
FOLLOWUP_MAX_WORDS = 160                  # longueur maximale d'une réponse
# Une question qui demande une décision d'achat ou de vente reçoit un refus fixe, sans appel au modèle.
FOLLOWUP_ADVICE_PATTERNS = (
    r"\bdois-?je\b", r"\bdevrais-?je\b", r"\bfaut-?il\b", r"\bje (?:peux|pourrais) (?:acheter|vendre)\b",
    r"\bcon(?:s|se)eill", r"\brecommand", r"\bmeilleur(?:e)? (?:action|placement|choix)\b",
    r"\bachet(?:er|e|ez)\b", r"\bvend(?:re|s|ez)\b",
)
FOLLOWUP_REFUSAL_FR = (
    "Cet outil est une simulation : il décrit l'adéquation entre une action et votre profil, "
    "mais il ne dit pas s'il faut acheter ou vendre. Vous pouvez demander pourquoi la couleur est ce qu'elle est, "
    "ce qui pèse le plus dans votre profil, ou ce qui change si le montant change."
)
FOLLOWUP_FAILURE_FR = "Je ne peux pas répondre de façon fiable à cette question. Utilisez les trois questions proposées."
# Définitions fixes (aucun chiffre) : seules sources de l'outil 'explain_term' de l'agent.
FOLLOWUP_GLOSSARY = {
    "volatilité": "La volatilité mesure à quel point le prix d'une action monte et descend d'un jour à l'autre.",
    "baisse maximale": "La baisse maximale est la plus grande perte observée entre un sommet et le creux qui le suit.",
    "risque de queue": "Le risque de queue (CVaR) est la perte moyenne les pires jours, ceux qui sont parmi les plus mauvais de la période.",
    "tolérance": "Votre tolérance au risque résume, sur une échelle de 0 à 100, le niveau de variation que vos choix passés et votre quiz montrent que vous acceptez.",
    "écart": "L'écart est la différence entre le score de risque de l'action et votre tolérance : plus il est grand et positif, plus l'action est risquée pour vous.",
    "confiance": "L'indice de confiance dit à quel point le résultat repose sur assez de données solides.",
    "esg": "ESG désigne les critères environnementaux, sociaux et de gouvernance d'une entreprise.",
    "fnb": "Un FNB est un fonds négocié en bourse qui regroupe plusieurs titres dans un seul produit.",
}

# ---------------------------------------------------------------------------
# Actualité et taux de change du jour (agent Actualité, outil dollar)
# ---------------------------------------------------------------------------
# Le classement gauche / neutre / droite est une ÉTIQUETTE ÉDITORIALE GÉNÉRALEMENT ATTRIBUÉE, pas une mesure ;
# elle sert à vérifier que plusieurs sensibilités confirment un événement. Reuters n'a pas de flux public :
# BBC News (Affaires) tient le rôle de source neutre.
NEWS_SOURCES = (
    {"id": "guardian", "name": "The Guardian", "orientation": "gauche", "lang": "en",
     "url": "https://www.theguardian.com/uk/business/rss"},
    {"id": "iris", "name": "IRIS", "orientation": "gauche", "lang": "fr",
     "url": "https://www.iris-france.org/feed/"},
    {"id": "bbc", "name": "BBC News (Affaires)", "orientation": "neutre", "lang": "en",
     "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    {"id": "cnbc", "name": "CNBC", "orientation": "neutre", "lang": "en",
     "url": "https://www.cnbc.com/id/10001147/device/rss/rss.html"},
    {"id": "yahoo", "name": "Yahoo Finance", "orientation": "neutre", "lang": "en",
     "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US", "per_ticker": True},
    {"id": "foxbusiness", "name": "Fox Business", "orientation": "droite", "lang": "en",
     "url": "https://moxie.foxbusiness.com/google-publisher/latest.xml"},
    {"id": "contrepoints", "name": "Contrepoints", "orientation": "droite", "lang": "fr",
     "url": "https://contrepoints.org/feed/"},
)
NEWS_USER_AGENT = "Mozilla/5.0 (compatible; agent-risque-demo/1.0)"
NEWS_PAGE_WAIT_S = 25.0                    # [ARBITRAIRE] attente maximale de l'analyse d'actualité avant d'afficher la page
NEWS_FETCH_TIMEOUT_S = 10                  # [ARBITRAIRE] délai par requête
NEWS_MAX_ARTICLES_PER_TICKER = 8           # [ARBITRAIRE] articles lus au plus par action
NEWS_ARTICLE_MAX_CHARS = 6000              # texte intégral conservé, tronqué à cette taille
NEWS_AGENT_MAX_ATTEMPTS = 2
NEWS_AGENT_MAX_TOKENS = 12000
NEWS_QUOTE_MIN_CHARS = 20
NEWS_QUOTE_MAX_CHARS = 300
# Types d'événements que l'agent peut déclarer (liste fermée : tout autre type est refusé).
NEWS_EVENT_TYPES = {
    "enquete_ou_poursuite": "Enquête, poursuite ou sanction",
    "resultats_decevants": "Résultats ou prévisions décevants",
    "changement_direction": "Départ ou changement de direction",
    "incident_operationnel": "Incident opérationnel (panne, rappel, accident)",
    "dette_ou_liquidite": "Dette, liquidité ou financement sous tension",
    "regulation_defavorable": "Règle ou décision publique défavorable",
    "choc_de_marche": "Choc de marché ou de secteur",
}
# Effet sur le score de risque d'une action (points sur 100). [ARBITRAIRE] Seuls les événements qui AUGMENTENT
# le risque comptent (asymétrie prudente) ; le total est plafonné.
NEWS_SEVERITY_POINTS = {1: 1.0, 2: 2.0, 3: 3.5}
NEWS_MAX_POINTS = 5.0
NEWS_MIN_SOURCES = 2                       # un événement ne compte que s'il est rapporté par 2 sources différentes
NEWS_VOLUME_POINTS = ((5, 2.0), (3, 1.0))  # [ARBITRAIRE] règle du « nombre » : (articles défavorables distincts, points), du plus grand au plus petit seuil
NEWS_DIVERGENCE_SPREAD = 2                 # écart de gravité entre sources à partir duquel elles « divergent »
NEWS_DIVERGENCE_MARGIN = 3.0               # points ajoutés à la marge d'incertitude quand les sources divergent
# Mots qui permettent de rattacher un article à une action (en plus du nom et du symbole).
NEWS_ALIASES = {
    "RY.TO": ("RBC", "Royal Bank"), "TD.TO": ("TD Bank", "Toronto-Dominion"), "MFC.TO": ("Manulife",),
    "ENB.TO": ("Enbridge",), "CNQ.TO": ("Canadian Natural",), "CNR.TO": ("Canadian National", "CN Rail"),
    "FTS.TO": ("Fortis",), "ATD.TO": ("Couche-Tard",), "SHOP.TO": ("Shopify",), "CSU.TO": ("Constellation Software",),
    "AAPL": ("Apple", "iPhone"), "MSFT": ("Microsoft",), "NVDA": ("Nvidia",), "GOOGL": ("Alphabet", "Google"),
    "AMZN": ("Amazon",), "TSLA": ("Tesla",), "JPM": ("JPMorgan", "JP Morgan"), "JNJ": ("Johnson & Johnson",),
    "PG": ("Procter & Gamble",), "XOM": ("Exxon",),
    "XIU.TO": ("TSX",), "SPY": ("S&P 500",), "QQQ": ("Nasdaq",), "ESGV": ("ESG fund", "ESG funds"),
    "XBB.TO": ("Canadian bond", "Bank of Canada"), "ZST.TO": ("Bank of Canada",), "AGG": ("bond market", "bond yields"),
    "TLT": ("Treasury yields", "Treasuries"), "GLD": ("gold price", "gold prices", "bullion"),
    "BTC-USD": ("Bitcoin",), "ETH-USD": ("Ethereum", "Ether"),
}
FX_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1"
FX_CACHE_SECONDS = 3600                    # le taux du jour est relu au plus une fois par heure

# Décimales conservées dans le JSON ; le score final affiché est arrondi à 1 décimale.
JSON_DECIMALS = 4
SCORE_DISPLAY_DECIMALS = 1


def fingerprint() -> str:
    """Empreinte stable des constantes ci-dessus (inscrite dans chaque profil)."""
    values = {
        name: value
        for name, value in sorted(globals().items())
        if name.isupper() and name not in ("DATA_DIR", "REPORT_CACHE_DIR", "APP_DATA_DIR")
    }
    payload = json.dumps(values, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
