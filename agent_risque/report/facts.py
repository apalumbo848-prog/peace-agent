"""Fiche de faits : la SEULE matière du rapport.

Chaque fait est une phrase courte, déjà correcte, avec son identifiant (F1, F2...),
son type (donnée, calcul, hypothèse, limite) et sa source. Le texte fixe et le
modèle de langage n'écrivent rien qui ne soit dans cette fiche ; le vérificateur
(verify.py) contrôle que chaque chiffre et chaque phrase s'y rattachent.
Tous les nombres viennent du dictionnaire de verdict (étape 3), jamais recalculés.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .. import combine, config
from ..asset_score import AssetRiskResult

TYPES = ("donnee", "calcul", "hypothese", "limite")

CLASS_FR = {
    "equity": "action",
    "etf_equity": "FNB d'actions",
    "etf_bond": "FNB d'obligations",
    "etf_commodity": "FNB de matières premières",
    "crypto": "cryptoactif",
}
COLOR_FR = {"vert": "vert", "jaune": "jaune", "rouge": "rouge"}


def fr(x: float, decimals: int = 0, signed: bool = False) -> str:
    """Nombre au format français (virgule décimale, sans séparateur de milliers)."""
    text = f"{abs(x):.{decimals}f}".replace(".", ",")
    if round(x, decimals) < 0:
        return "-" + text
    if signed and round(x, decimals) > 0:
        return "+" + text
    return text


@dataclass(frozen=True)
class Fact:
    id: str
    key: str
    section: str
    type: str
    text: str                      # version intermédiaire (défaut)
    plain: str | None = None       # version débutant (mots simples)
    expert: str | None = None      # version avancé (termes financiers)
    min_level: int = 0             # 0 = tous, 1 = intermédiaire et plus, 2 = avancé seulement
    priority: int = 50             # plus petit = plus important
    must_cite: bool = False        # doit apparaître dans le rapport
    source: str = ""

    def text_for(self, level: str) -> str:
        if level == "debutant" and self.plain:
            return self.plain
        if level == "avance" and self.expert:
            return self.expert
        return self.text


@dataclass
class FactSheet:
    level: str
    user_id: str
    ticker: str
    as_of: str
    final_color: str
    facts: list[Fact]

    def level_index(self) -> int:
        return config.REPORT_LEVELS.index(self.level)

    def by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}

    def by_key(self) -> dict[str, Fact]:
        return {f.key: f for f in self.facts}

    def selected(self) -> dict[str, list[Fact]]:
        """Faits retenus par section pour ce niveau (plafond de phrases ; obligatoires toujours)."""
        idx = self.level_index()
        caps = config.REPORT_MAX_SENTENCES[self.level]
        out: dict[str, list[Fact]] = {}
        for section, _ in config.REPORT_SECTION_TITLES:
            pool = [f for f in self.facts if f.section == section and f.min_level <= idx]
            pool.sort(key=lambda f: (f.priority, f.id))
            must = [f for f in pool if f.must_cite]
            rest = [f for f in pool if not f.must_cite]
            keep = must + rest[:max(0, caps[section] - len(must))]
            out[section] = sorted(keep, key=lambda f: (f.priority, f.id))
        return out

    def to_dict(self) -> dict:
        return {"level": self.level, "user_id": self.user_id, "ticker": self.ticker, "as_of": self.as_of,
                "final_color": self.final_color, "facts": [asdict(f) for f in self.facts]}


# Textes par mesure : (intermédiaire, débutant, avancé), {x} = valeur brute, {p} = points, {t} = tolérance.
_COMPONENT_TEXTS = {
    "volatility": (
        "Volatilité : les prix varient en moyenne de {x} % par an, soit {p} points sur 100.",
        "Les prix de cette action varient beaucoup : environ {x} % par an.",
        "Volatilité annualisée (récente et longue durée mélangées) de {x} %, soit {p} points sur 100.",
    ),
    "drawdown": (
        "Baisse maximale : l'action a déjà perdu jusqu'à {x} % depuis un sommet, soit {p} points sur 100.",
        "Elle a déjà perdu jusqu'à {x} % de sa valeur entre un sommet et un creux.",
        "Baisse maximale de {x} % sur la période, soit {p} points sur 100.",
    ),
    "tail_risk": (
        "Pires jours : les 5 % de jours les plus mauvais coûtent en moyenne {x} %, soit {p} points sur 100.",
        "Ses pires journées font perdre en moyenne {x} %.",
        "Perte moyenne conditionnelle (CVaR 95 %) de {x} % par jour, soit {p} points sur 100.",
    ),
    "recent_stress": (
        "Situation actuelle : l'action est {x} % sous son plus haut des 12 derniers mois, soit {p} points sur 100.",
        "Aujourd'hui, elle est {x} % sous son plus haut de l'année.",
        "Écart de {x} % sous le plus haut des 252 dernières séances, soit {p} points sur 100.",
    ),
}
_COMPONENT_DECIMALS = {"volatility": 1, "drawdown": 1, "tail_risk": 2, "recent_stress": 1}
_COMPONENT_ORDER = ("volatility", "drawdown", "tail_risk", "recent_stress")


def build_fact_sheet(verdict: dict, profile: dict, asset: AssetRiskResult, level: str) -> FactSheet:
    if level not in config.REPORT_LEVELS:
        raise ValueError(f"Niveau inconnu : {level}")
    raw: list[dict] = []

    def add(key, section, type_, text, plain=None, expert=None, min_level=0, priority=50,
            must_cite=False, source=""):
        raw.append(dict(key=key, section=section, type=type_, text=text, plain=plain, expert=expert,
                        min_level=min_level, priority=priority, must_cite=must_cite, source=source))

    user, asset_v = verdict["user"], verdict["asset"]
    gap, tol = verdict["gap"], user["effective_tolerance"]
    risk_color, final_color = verdict["risk_color"], verdict["final_color"]
    thr = verdict["thresholds"]

    # --- En bref ---------------------------------------------------------
    unit = "point" if abs(round(gap)) <= 1 else "points"
    prefix = (f"Verdict {risk_color} : " if risk_color == final_color
              else f"Pour le risque seul, le verdict est {risk_color} : ")
    add("headline", "en_bref", "calcul", prefix + config.VERDICT_HEADLINES[risk_color].format(gap=gap, unit=unit),
        priority=1, must_cite=True, source="étape 3 : comparaison profil / action")
    if final_color != risk_color:
        add("final_color", "en_bref", "calcul",
            f"La couleur finale est {final_color} parce que vos contraintes relèvent le verdict "
            f"({risk_color} pour le risque seul).", priority=2, must_cite=True,
            source="étape 3 : contraintes")
    add("scores", "en_bref", "calcul",
        f"Le score de risque de l'action est de {fr(asset_v['score'], 0)} sur 100 et votre tolérance est de "
        f"{fr(tol, 0)} sur 100.",
        plain=f"L'action a un niveau de risque de {fr(asset_v['score'], 0)} sur 100 ; le vôtre se situe à "
              f"{fr(tol, 0)} sur 100.",
        priority=3, source="étapes 1 et 2")
    if verdict["too_safe"]:
        add("too_safe", "en_bref", "calcul", config.VERDICT_TOO_SAFE_MESSAGE, priority=4, must_cite=True,
            source="étape 3 : comparaison")
    add("confidence", "en_bref", "calcul",
        f"La confiance dans ce résultat est {verdict['confidence']['label']}.",
        priority=6, source="étape 3 : confiance")
    add("thresholds", "en_bref", "hypothese",
        f"Seuils choisis par l'équipe : vert jusqu'à {fr(thr['green_max_gap'], 0, True)} points d'écart, jaune "
        f"jusqu'à {fr(thr['yellow_max_gap'], 0, True)}, rouge au-delà.",
        min_level=1, priority=7, source="config.py")

    # --- Pourquoi --------------------------------------------------------
    drivers = {d["key"]: d for d in verdict["drivers"]}
    exceeding = [d for d in verdict["drivers"] if d["excess_over_tolerance"] > 0]
    if exceeding:
        for rank, d in enumerate(exceeding[:3]):
            share = fr(100 * d["share_of_excess"], 0)
            label = d["label"].lower()
            add(f"why_{d['key']}", "pourquoi", "calcul",
                f"{d['label']} : {fr(d['asset_points'], 0)} points sur 100, au-dessus de votre tolérance de "
                f"{fr(tol, 0)} ; cette mesure explique {share} % de l'écart.",
                plain=f"La mesure « {label} » de l'action dépasse votre tolérance et explique {share} % de l'écart.",
                priority=10 + rank, source="étape 3 : facteurs de l'écart")
    else:
        add("no_excess", "pourquoi", "calcul",
            "Aucune des quatre mesures de risque de l'action ne dépasse votre tolérance.",
            priority=10, source="étape 3 : facteurs de l'écart")
    ev = verdict["profile_evidence"]
    if ev["volatility"]:
        e = ev["volatility"]
        add("evidence_vol", "pourquoi", "donnee",
            (f"Votre portefeuille a varié d'environ {fr(e['user_purchased_vol_pct'], 1)} % par an ; "
             f"celle de l'action est de {fr(e['asset_vol_pct'], 1)} %.") if e.get("basis") == "portfolio" else
            (f"Vos achats passés avaient une volatilité moyenne de {fr(e['user_purchased_vol_pct'], 1)} % ; "
             f"celle de l'action est de {fr(e['asset_vol_pct'], 1)} %."),
            plain=f"Votre portefeuille variait d'environ {fr(e['user_purchased_vol_pct'], 1)} % par an ; "
                  f"cette action varie d'environ {fr(e['asset_vol_pct'], 1)} %.",
            min_level=0, priority=20, source="étape 1 : volatilité de l'historique")
    if ev.get("accepted_loss"):
        e = ev["accepted_loss"]
        add("evidence_accepted_loss", "pourquoi", "donnee",
            f"Dans vos mises en situation, vous acceptez en moyenne une perte d'environ {fr(e['user_accepted_loss_pct'], 0)} % ; "
            f"cette action a déjà perdu jusqu'à {fr(e['asset_max_drawdown_pct'], 1)} % au pire.",
            plain=f"Vous acceptez en moyenne de perdre environ {fr(e['user_accepted_loss_pct'], 0)} % ; "
                  f"cette action a déjà perdu jusqu'à {fr(e['asset_max_drawdown_pct'], 1)} %.",
            min_level=0, priority=19, source="étape 1 : mises en situation")
    if ev.get("loss_endured"):
        e = ev["loss_endured"]
        add("evidence_loss_endured", "pourquoi", "donnee",
            f"Votre portefeuille a déjà traversé une baisse de {fr(e['user_worst_portfolio_drop_pct'], 0)} % ; "
            f"cette action a déjà perdu jusqu'à {fr(e['asset_max_drawdown_pct'], 1)} % au pire.",
            min_level=1, priority=22, source="étape 1 : pertes traversées")
    if ev["drop_reaction"]:
        e = ev["drop_reaction"]
        add("evidence_drop", "pourquoi", "donnee",
            f"Face à des baisses de 10 % ou plus, votre réaction passée obtient {fr(e['user_reaction_score'], 0)} sur 100 ; "
            f"cette action a déjà perdu jusqu'à {fr(e['asset_max_drawdown_pct'], 1)} % au pire.",
            min_level=1, priority=21, source="étape 1 : réaction aux baisses")

    # --- Votre profil ----------------------------------------------------
    comp = profile["components"]
    add("user_score", "profil", "calcul", f"Votre tolérance au risque est de {fr(user['score'], 0)} sur 100.",
        priority=30, source="étape 1 : score du profil")
    pillar = combine.second_pillar(profile)
    p2 = comp[pillar["key"]]
    wh, wq = 100 * comp["history"]["effective_weight"], 100 * p2["effective_weight"]
    if comp["history"]["score"] is not None and p2["score"] is not None:
        add("composition", "profil", "calcul",
            f"Ce score combine vos opérations passées ({fr(comp['history']['score'], 0)}, poids {fr(wh, 0)} %) "
            f"et {pillar['your']} ({fr(p2['score'], 0)}, poids {fr(wq, 0)} %).",
            plain=f"Ce score vient de vos opérations passées et de {pillar['answers']}.",
            priority=31, source="étape 1 : combinaison")
    elif p2["score"] is not None:
        add("composition", "profil", "calcul",
            f"Ce score repose uniquement sur {pillar['your']} ({fr(p2['score'], 0)}), faute d'opérations suffisantes.",
            priority=31, source="étape 1 : combinaison")
    add("profile_confidence", "profil", "calcul",
        f"La confiance dans votre profil est {profile['confidence']['label']}.",
        expert=f"La confiance dans votre profil est {profile['confidence']['label']}, fondée sur "
               f"{profile['history']['n_valid_trades']} opérations valides.",
        priority=32, source="étape 1 : confiance")
    for w in profile["warnings"]:
        if w.startswith("Écart notable"):
            add("divergence", "profil", "limite", w, priority=33, must_cite=True, source="étape 1")
    if not verdict["robustness"]["robust"]:
        which = " ou que ".join("votre historique" if n == "history" else pillar["answers"]
                                for n in verdict["robustness"]["sensitive_to"])
        add("robustness", "profil", "limite",
            f"Le verdict dépend de la source du profil : il change si l'on ne regarde que {which}.",
            priority=34, must_cite=True, source="étape 3 : robustesse")

    # --- L'action --------------------------------------------------------
    cls = CLASS_FR.get(asset.asset_class, asset.asset_class)
    add("identity", "action", "donnee",
        f"{asset.name} ({asset.ticker}) est un(e) {cls} du secteur « {asset.sector} » ; ses prix sont en {asset.currency}.",
        priority=40, must_cite=True, source="assets_universe.csv")
    src = next((s for s in asset.data_sources if s["file"] == "prices_daily.csv"), None)
    retrieved = f", extraction du {src['retrieved_on']}" if src else ""
    source_name = ("Yahoo Finance (bibliothèque yfinance)" if src and "Yahoo" in src["source"]
                   else (src["source"] if src else "données fournies"))
    add("window", "action", "donnee",
        f"Les mesures couvrent du {asset.window_start} au {asset.window_end} ({asset.n_returns} variations "
        f"journalières) ; source : {source_name}{retrieved}.",
        min_level=1, priority=41, source="prices_daily.csv")
    for i, key in enumerate(_COMPONENT_ORDER):
        d = drivers.get(key)
        if d is None:
            continue
        tpl, tpl_plain, tpl_expert = _COMPONENT_TEXTS[key]
        values = dict(x=fr(d["raw_value"], _COMPONENT_DECIMALS[key]), p=fr(d["asset_points"], 0))
        add(f"component_{key}", "action", "calcul", tpl.format(**values), plain=tpl_plain.format(**values),
            expert=tpl_expert.format(**values), priority=42 + i, source="étape 2 : score de l'action")

    # --- Contraintes -----------------------------------------------------
    for i, c in enumerate(verdict["constraints"]):
        # Violations, alertes et préférences non vérifiables (ex. ESG) doivent toujours apparaître.
        flagged = c["status"] in ("violation", "attention", "non_verifiable")
        add(f"constraint_{c['key']}", "contraintes", "limite" if c["status"] == "non_verifiable" else "calcul",
            c["message"], priority=60 + (0 if flagged else 10) + i, must_cite=flagged,
            source="étape 3 : contraintes")

    # --- Limites et hypothèses ------------------------------------------
    for i, w in enumerate(verdict["warnings"]):
        news = w.startswith("Actualité")
        add(f"limit_{i}", "limites", "limite", w, priority=80 + (0 if news else 1) + i,
            must_cite=news or w.startswith("Changement de régime") or w.startswith("Anomalie"),
            source="étape 2 : avertissements")
    for i, text in enumerate(config.REPORT_ASSUMPTIONS_FR):
        add(f"assumption_{i}", "limites", "hypothese", text, min_level=1, priority=90 + i, source="config.py")

    facts = [Fact(id=f"F{n}", **r) for n, r in enumerate(raw, start=1)]
    return FactSheet(level=level, user_id=verdict["user_id"], ticker=verdict["ticker"],
                     as_of=verdict["as_of"], final_color=final_color, facts=facts)
