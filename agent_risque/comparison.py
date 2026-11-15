"""Étape 3 : comparaison profil / action et verdict vert, jaune ou rouge.

Fonction pure, appelée uniquement à l'ouverture de la page d'achat. Aucun modèle
d'IA : formules et règles explicites de config.py. Le verdict décrit une adéquation
entre le risque de l'action et la tolérance déclarée ; ce n'est pas un conseil.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from . import combine, config, constraints, data_access, history_score
from .asset_score import AssetRiskResult
from .transactions import Transaction, validate_and_sort

COLORS = ("vert", "jaune", "rouge")


def color_for_gap(gap: float) -> str:
    """Couleur du risque pour un écart donné (action - tolérance effective)."""
    if gap <= config.VERDICT_GREEN_MAX_GAP:
        return "vert"
    if gap <= config.VERDICT_YELLOW_MAX_GAP:
        return "jaune"
    return "rouge"


def _effective_tolerance(user_score: float, user_confidence: float, margin: float | None = None) -> float:
    """Tolérance retenue pour le verdict = score - marge d'incertitude (plus prudent qu'un score brut).

    v1 : marge = 15 x (1 - confiance). v2 : le profil fournit sa propre marge (confiance + écart entre piliers)."""
    if margin is None:
        margin = config.VERDICT_MAX_UNCERTAINTY_MARGIN * (1.0 - user_confidence)
    return max(0.0, user_score - margin)


def _drivers(asset: AssetRiskResult, tolerance: float) -> list[dict]:
    rows = []
    for c in asset.components:
        if not c.available:
            continue
        excess = max(0.0, c.points - tolerance)
        rows.append({"key": c.key, "label": c.label, "asset_points": c.points,
                     "excess_over_tolerance": excess, "weighted_excess": c.effective_weight * excess,
                     "raw_value": c.raw_value, "raw_unit": c.raw_unit})
    total = sum(r["weighted_excess"] for r in rows)
    for r in rows:
        r["share_of_excess"] = (r["weighted_excess"] / total) if total > 0 else 0.0
    return sorted(rows, key=lambda r: (-r["weighted_excess"], r["key"]))


def _profile_evidence(profile: dict, asset: AssetRiskResult) -> dict:
    """Juxtapositions factuelles (sans formule) entre le comportement passé et l'action."""
    by_key = {i["key"]: i for i in profile["history"]["indicators"]}
    comp = {c.key: c for c in asset.components}
    evidence: dict = {"volatility": None, "drop_reaction": None, "loss_endured": None, "accepted_loss": None}
    basis = "portfolio" if "portfolio_vol" in by_key else "purchases"
    vol_user = by_key.get("portfolio_vol") or by_key.get("volatility")
    if vol_user and vol_user["available"]:
        evidence["volatility"] = {
            "basis": basis, "user_purchased_vol_pct": vol_user["raw_value"], "user_vol_points": vol_user["score"],
            "asset_vol_pct": comp["volatility"].raw_value, "asset_vol_points": comp["volatility"].points}
    loss_user = by_key.get("loss_endured")
    if loss_user and loss_user["available"]:
        evidence["loss_endured"] = {"user_worst_portfolio_drop_pct": loss_user["raw_value"],
                                    "asset_max_drawdown_pct": comp["drawdown"].raw_value}
    items = profile.get("situations", {}).get("items") or []
    if items:
        evidence["accepted_loss"] = {
            "user_accepted_loss_pct": sum(i["weight"] * i["max_accepted_loss_pct"] for i in items),
            "asset_max_drawdown_pct": comp["drawdown"].raw_value}
    drop_user = by_key.get("drop_reaction")
    if drop_user and drop_user["available"]:
        evidence["drop_reaction"] = {
            "user_reaction_score": drop_user["score"], "user_events_observed": drop_user["raw_value"],
            "asset_max_drawdown_pct": comp["drawdown"].raw_value}
    return evidence


def compare(profile: dict, asset: AssetRiskResult, planned_amount_cad: float | None = None) -> dict:
    """Verdict complet. `profile` vient de combine.compute_user_profile, `asset` de score_asset.

    Les deux doivent avoir la même date de référence. `planned_amount_cad` (optionnel)
    permet d'évaluer la concentration après achat.
    """
    if profile["as_of"] != asset.as_of:
        raise ValueError(f"Dates différentes : profil au {profile['as_of']}, action au {asset.as_of}.")
    as_of = date.fromisoformat(profile["as_of"])

    user_score = profile["final_score"]
    user_conf = profile["confidence"]["value"]
    margin = profile.get("uncertainty", {}).get("margin")             # fourni par le modèle v2
    news_extra = float((asset.news or {}).get("extra_margin") or 0.0)  # sources d'actualité qui divergent
    if news_extra:
        base_margin = margin if margin is not None else config.VERDICT_MAX_UNCERTAINTY_MARGIN * (1.0 - user_conf)
        margin = base_margin + news_extra
    tolerance = _effective_tolerance(user_score, user_conf, margin)
    gap = asset.score - tolerance
    risk_color = color_for_gap(gap)
    too_safe = gap <= config.VERDICT_TOO_SAFE_GAP

    # Robustesse : verdict avec l'historique seul et avec le quiz seul.
    variants: dict[str, dict] = {}
    pillar = combine.second_pillar(profile)
    for name in ("history", pillar["key"]):
        s = profile[name]["score"]
        if s is not None:
            t = _effective_tolerance(s, user_conf, margin)
            variants[name] = {"user_score": s, "gap": asset.score - t, "color": color_for_gap(asset.score - t)}
    differing = sorted(n for n, v in variants.items() if v["color"] != risk_color)
    robustness = {"robust": not differing, "sensitive_to": differing, "variants": variants}

    # Contraintes.
    declared, warnings = constraints.parse_declared(profile["inputs"].get("declared_not_scored"))
    txs = [Transaction.from_dict(t) for t in profile["inputs"]["transactions"]]
    trades, _ = validate_and_sort(txs, as_of)
    values, val_warnings = history_score.current_portfolio_values(trades, as_of)
    warnings += val_warnings
    asset_info = data_access.get_asset(asset.ticker)
    constraint_results = constraints.evaluate_constraints(declared, asset_info, asset.score, values, planned_amount_cad)
    final_rank = max(COLORS.index(risk_color), constraints.worst_color_rank(constraint_results))
    final_color = COLORS[final_rank]

    # Confiance du verdict : la plus basse des deux.
    conf_value = min(user_conf, asset.confidence["value"])
    conf_label = combine.lowest_label(profile["confidence"]["label"], asset.confidence["label"])

    # Phrases fixes (repli déterministe pour le rapport).
    unit = "point" if abs(round(gap)) <= 1 else "points"
    summary = [config.VERDICT_HEADLINES[risk_color].format(gap=gap, unit=unit)]
    if too_safe:
        summary.append(config.VERDICT_TOO_SAFE_MESSAGE)
    for r in constraint_results:
        if r.status in (constraints.STATUS_VIOLATION, constraints.STATUS_ATTENTION):
            summary.append(r.message)
    if not robustness["robust"]:
        summary.append("Ce résultat dépend de la source du profil : il change si l'on ne regarde que "
                       + " ou que ".join("votre historique" if n == "history" else pillar["answers"]
                                         for n in differing) + ".")

    result = {
        "user_id": profile["user_id"],
        "ticker": asset.ticker,
        "as_of": profile["as_of"],
        "config": {"version": config.CONFIG_VERSION, "fingerprint": config.fingerprint()},
        "final_color": final_color,
        "risk_color": risk_color,
        "gap": gap,
        "too_safe": too_safe,
        "user": {"score": user_score, "confidence": user_conf, "effective_tolerance": tolerance},
        "asset": {"score": asset.score, "confidence": asset.confidence["value"], "name": asset.name,
                  "asset_class": asset.asset_class, "sector": asset.sector},
        "thresholds": {"green_max_gap": config.VERDICT_GREEN_MAX_GAP,
                       "yellow_max_gap": config.VERDICT_YELLOW_MAX_GAP,
                       "too_safe_gap": config.VERDICT_TOO_SAFE_GAP},
        "robustness": robustness,
        "news": asset.news,
        "drivers": _drivers(asset, tolerance),
        "profile_evidence": _profile_evidence(profile, asset),
        "constraints": [asdict(r) for r in constraint_results],
        "confidence": {"value": conf_value, "label": conf_label},
        "summary_fr": summary,
        "warnings": warnings + asset.warnings,
        "disclaimers": list(asset.disclaimers),
    }
    return combine.round_floats(result, config.JSON_DECIMALS)
