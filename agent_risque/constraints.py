"""Contraintes de l'investisseur (couche de gouvernance, règles fixes, sans IA).

Les contraintes ne changent JAMAIS le score de risque : elles s'affichent à côté et
peuvent relever la couleur finale (violation = rouge, attention = jaune).

Champs déclarés lus (format normalisé) :
    {"horizon_years": [min, max_ou_None],
     "exclusions": {"asset_classes": [...], "sectors": [...], "tickers": [...]},
     "preferences": ["ESG", ...]}
Un format non reconnu est ignoré avec un avertissement : rien n'est deviné.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import config, data_access

STATUS_OK = "ok"
STATUS_ATTENTION = "attention"
STATUS_VIOLATION = "violation"
STATUS_NOT_EVALUATED = "non_evaluee"
STATUS_NOT_VERIFIABLE = "non_verifiable"

# Rang de couleur associé à chaque statut (0 = aucune couleur imposée).
STATUS_COLOR_RANK = {STATUS_VIOLATION: 2, STATUS_ATTENTION: 1}


@dataclass(frozen=True)
class Declared:
    horizon_declared: bool = False
    horizon_min: float | None = None
    horizon_max: float | None = None          # None = sans limite supérieure
    excluded_classes: tuple[str, ...] = ()
    excluded_sectors: tuple[str, ...] = ()
    excluded_tickers: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()
    experience: str = config.REPORT_DEFAULT_LEVEL   # niveau de détail du rapport (étape 4)


@dataclass
class ConstraintResult:
    key: str
    label: str
    status: str
    message: str
    details: dict = field(default_factory=dict)


def _str_list(value, name: str, warnings: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return tuple(value)
    warnings.append(f"Champ déclaré '{name}' ignoré : format non reconnu (liste de textes attendue).")
    return ()


def parse_declared(raw: dict | None) -> tuple[Declared, list[str]]:
    warnings: list[str] = []
    raw = raw or {}

    horizon_declared, hmin, hmax = False, None, None
    h = raw.get("horizon_years")
    if h is not None:
        ok = (isinstance(h, (list, tuple)) and len(h) == 2
              and isinstance(h[0], (int, float)) and not isinstance(h[0], bool)
              and (h[1] is None or (isinstance(h[1], (int, float)) and not isinstance(h[1], bool))))
        if ok:
            horizon_declared, hmin, hmax = True, float(h[0]), (None if h[1] is None else float(h[1]))
        else:
            warnings.append("Champ déclaré 'horizon_years' ignoré : format attendu [min, max] "
                            "(max peut être null).")

    excl = raw.get("exclusions")
    classes = sectors = tickers = ()
    if excl is not None:
        if isinstance(excl, dict):
            classes = _str_list(excl.get("asset_classes"), "exclusions.asset_classes", warnings)
            sectors = _str_list(excl.get("sectors"), "exclusions.sectors", warnings)
            tickers = _str_list(excl.get("tickers"), "exclusions.tickers", warnings)
        else:
            warnings.append("Champ déclaré 'exclusions' ignoré : format attendu "
                            "{asset_classes, sectors, tickers}.")

    prefs = _str_list(raw.get("preferences"), "preferences", warnings)

    experience = config.REPORT_DEFAULT_LEVEL
    if raw.get("experience") is not None:
        if raw["experience"] in config.REPORT_LEVELS:
            experience = raw["experience"]
        else:
            warnings.append(f"Champ déclaré 'experience' ignoré : valeurs permises {list(config.REPORT_LEVELS)}.")
    return Declared(horizon_declared, hmin, hmax, classes, sectors, tickers, prefs, experience), warnings


def _norm(values: tuple[str, ...]) -> set[str]:
    return {v.strip().lower() for v in values}


def _exclusions(declared: Declared, asset: data_access.Asset) -> ConstraintResult:
    label = "Exclusions déclarées"
    hits = []
    if asset.asset_class.lower() in _norm(declared.excluded_classes):
        hits.append(f"la classe d'actifs « {asset.asset_class} »")
    if asset.sector.lower() in _norm(declared.excluded_sectors):
        hits.append(f"le secteur « {asset.sector} »")
    if asset.ticker.lower() in _norm(declared.excluded_tickers):
        hits.append(f"le titre {asset.ticker}")
    if hits:
        return ConstraintResult("exclusions", label, STATUS_VIOLATION,
                                "Vous avez demandé d'exclure " + " et ".join(hits) + " : cet achat ne respecte pas cette exclusion.",
                                {"matches": hits})
    return ConstraintResult("exclusions", label, STATUS_OK, "Aucune de vos exclusions déclarées ne concerne cette action.")


def _horizon(declared: Declared, asset_score: float) -> ConstraintResult:
    label = "Horizon de placement"
    if not declared.horizon_declared:
        return ConstraintResult("horizon", label, STATUS_NOT_EVALUATED, "Horizon de placement non déclaré.")
    short = declared.horizon_max is not None and declared.horizon_max <= config.CONSTRAINT_SHORT_HORIZON_YEARS
    if short and asset_score >= config.CONSTRAINT_HIGH_RISK_ASSET_SCORE:
        return ConstraintResult(
            "horizon", label, STATUS_ATTENTION,
            f"Votre horizon ({declared.horizon_min:g} à {declared.horizon_max:g} ans) est court et "
            f"l'action présente un risque élevé (score {asset_score:.0f}) : une baisse pourrait ne pas "
            "avoir le temps d'être récupérée.",
            {"horizon_max": declared.horizon_max, "asset_score": asset_score})
    return ConstraintResult("horizon", label, STATUS_OK, "Le risque de l'action est compatible avec l'horizon déclaré.")


def _concentration(asset: data_access.Asset, current_values: dict[str, float],
                   planned_amount_cad: float | None) -> ConstraintResult:
    label = "Concentration après achat"
    if planned_amount_cad is None:
        return ConstraintResult("concentration", label, STATUS_NOT_EVALUATED,
                                "Montant de l'achat non fourni : concentration non évaluée.")
    before = math.fsum(current_values.values())
    if before <= 0:
        return ConstraintResult("concentration", label, STATUS_NOT_EVALUATED,
                                "Portefeuille vide : la concentration n'a pas de sens pour un premier achat.")
    values = dict(current_values)
    values[asset.ticker] = values.get(asset.ticker, 0.0) + planned_amount_cad
    total = math.fsum(values.values())

    single = None
    if asset.asset_class in config.SINGLE_NAME_CLASSES:
        single = values[asset.ticker] / total
    sector_weight = None
    if asset.asset_class not in config.DIVERSIFIED_ETF_CLASSES:
        sector_weight = math.fsum(
            v for t, v in values.items()
            if data_access.get_asset(t) is not None
            and data_access.get_asset(t).sector == asset.sector
            and data_access.get_asset(t).asset_class not in config.DIVERSIFIED_ETF_CLASSES
        ) / total
    details = {"single_name_weight": single, "sector_weight": sector_weight, "sector": asset.sector}

    if single is not None and single >= config.SINGLE_NAME_MAX_WEIGHT:
        return ConstraintResult("concentration", label, STATUS_VIOLATION,
                                f"Après cet achat, {asset.ticker} représenterait {single:.0%} de votre portefeuille "
                                f"(limite de {config.SINGLE_NAME_MAX_WEIGHT:.0%}).", details)
    if single is not None and single > config.CONSTRAINT_SINGLE_NAME_ATTENTION:
        return ConstraintResult("concentration", label, STATUS_ATTENTION,
                                f"Après cet achat, {asset.ticker} représenterait {single:.0%} de votre portefeuille "
                                f"(seuil d'attention de {config.CONSTRAINT_SINGLE_NAME_ATTENTION:.0%}).", details)
    if sector_weight is not None and sector_weight > config.CONSTRAINT_SECTOR_ATTENTION:
        return ConstraintResult("concentration", label, STATUS_ATTENTION,
                                f"Après cet achat, le secteur « {asset.sector} » représenterait {sector_weight:.0%} "
                                f"de votre portefeuille (seuil d'attention de {config.CONSTRAINT_SECTOR_ATTENTION:.0%}).",
                                details)
    return ConstraintResult("concentration", label, STATUS_OK,
                            "La répartition du portefeuille reste diversifiée après cet achat.", details)


# Préférences vérifiables avec les données : mot déclaré -> (champ de l'actif, valeur(s) acceptée(s)). Une préférence est un
# souhait, pas une limite : elle n'influence jamais la couleur (statut « ok » dans les deux cas, le message dit ce qu'il en est).
_PREFERENCE_MATCH = {
    "technologie": ("sector", {"information technology"}),
    "tech": ("sector", {"information technology"}),
    "crypto": ("asset_class", {"crypto"}),
    "cryptomonnaie": ("asset_class", {"crypto"}),
    "énergie": ("sector", {"energy"}),
    "santé": ("sector", {"health care"}),
    "finance": ("sector", {"financials"}),
    "obligations": ("asset_class", {"etf_bond"}),
    "or": ("sector", {"gold"}),
}


def _preferences(declared: Declared, asset: data_access.Asset) -> list[ConstraintResult]:
    results = []
    for pref in declared.preferences:
        key, label = pref.strip().lower(), f"Préférence : {pref}"
        rule = _PREFERENCE_MATCH.get(key)
        if rule:
            field_name, accepted = rule
            value = getattr(asset, field_name)
            if value.lower() in accepted:
                msg = f"Cette action correspond à votre préférence « {pref} » ({value})."
            else:
                msg = (f"Cette action ne relève pas de votre préférence « {pref} » ({value}). "
                       "Une préférence est un souhait : elle ne change pas la couleur du verdict.")
            results.append(ConstraintResult(f"preference:{pref}", label, STATUS_OK, msg, {"matches": value.lower() in accepted}))
            continue
        if key == "esg":
            if "esg-screened" in asset.sector.lower():
                msg = "Ce fonds suit un indice filtré sur des critères ESG : il correspond à votre préférence ESG."
                results.append(ConstraintResult(f"preference:{pref}", label, STATUS_OK, msg, {"matches": True}))
                continue
            msg = ("Préférence ESG : le jeu de données n'a aucune note ESG par entreprise, donc cette action ne peut pas être vérifiée.")
            label = "Préférence ESG : pas de note ESG dans nos données, impossible de vérifier"
        else:
            msg = f"Préférence « {pref} » déclarée : le jeu de données ne contient rien qui permette de la vérifier."
            label = f"Préférence « {pref} » : pas de données pour la vérifier"
        results.append(ConstraintResult(f"preference:{pref}", label, STATUS_NOT_VERIFIABLE, msg))
    return results


def evaluate_constraints(declared: Declared, asset: data_access.Asset, asset_score: float,
                         current_values: dict[str, float],
                         planned_amount_cad: float | None) -> list[ConstraintResult]:
    if planned_amount_cad is not None and not planned_amount_cad > 0:
        raise ValueError("Le montant prévu de l'achat doit être strictement positif.")
    return [
        _exclusions(declared, asset),
        _horizon(declared, asset_score),
        _concentration(asset, current_values, planned_amount_cad),
        *_preferences(declared, asset),
    ]


def worst_color_rank(results: list[ConstraintResult]) -> int:
    return max((STATUS_COLOR_RANK.get(r.status, 0) for r in results), default=0)
