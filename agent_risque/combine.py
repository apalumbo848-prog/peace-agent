"""Combinaison historique + quiz, indice de confiance, et profil complet.

Poids effectifs : l'historique pèse HISTORY_WEIGHT_BASE (50 %) quand il est
pleinement fiable ; avec peu de transactions, ce poids baisse linéairement et le
quiz compense. Le score final est une formule explicite, décomposable.
"""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import date

from . import config, history_score, history_v2, quiz, situations
from .transactions import Transaction, validate_and_sort


def confidence_label(value: float) -> str:
    if value < config.CONFIDENCE_LABEL_LOW_MAX:
        return "faible"
    if value < config.CONFIDENCE_LABEL_MEDIUM_MAX:
        return "moyenne"
    return "élevée"


LABEL_ORDER = ("faible", "moyenne", "élevée")


def lowest_label(*labels: str) -> str:
    """Étiquette la plus basse (la moins confiante) parmi celles fournies."""
    return min(labels, key=LABEL_ORDER.index)


def combine_scores(history: history_score.HistoryResult, quiz_result: quiz.QuizResult) -> dict:
    """Combine les deux scores. Lève ValueError si aucun des deux n'est disponible."""
    h, q = history.score, quiz_result.score
    if h is None and q is None:
        raise ValueError("Impossible de calculer un score : ni historique exploitable, ni réponse au quiz.")

    # Fiabilité de l'historique : nombre de transactions ET couverture des indicateurs.
    history_reliability = 0.0 if h is None else (
        min(1.0, history.n_trades / config.N_TRANSACTIONS_FULL) * history.coverage
    )
    if q is None:
        w_h, w_q = 1.0, 0.0
    elif h is None:
        w_h, w_q = 0.0, 1.0
    else:
        w_h = config.HISTORY_WEIGHT_BASE * history_reliability
        w_q = 1.0 - w_h

    history_part = 0.0 if h is None else w_h * h
    quiz_part = 0.0 if q is None else w_q * q
    final = history_part + quiz_part

    quiz_completeness = quiz_result.n_answered / quiz_result.n_questions
    gap = abs(h - q) if (h is not None and q is not None) else None
    agreement = 0.0 if gap is None else 1.0 - min(1.0, gap / config.AGREEMENT_GAP_MAX)
    cw = config.CONFIDENCE_WEIGHTS
    confidence = (cw["quiz_completeness"] * quiz_completeness
                  + cw["history_reliability"] * history_reliability
                  + cw["agreement"] * agreement)

    warnings: list[str] = []
    if gap is not None and gap >= config.DIVERGENCE_WARNING_GAP:
        direction = "plus tolérant" if q > h else "plus prudent"
        warnings.append(
            f"Écart notable entre l'historique ({h:.0f}) et le quiz ({q:.0f}) : "
            f"l'utilisateur se déclare {direction} que son comportement passé."
        )

    return {
        "final_score": final,
        "final_score_display": round(final, config.SCORE_DISPLAY_DECIMALS),
        "components": {
            "history": {"score": h, "effective_weight": w_h, "contribution": history_part},
            "quiz": {"score": q, "effective_weight": w_q, "contribution": quiz_part},
        },
        "confidence": {
            "value": confidence,
            "label": confidence_label(confidence),
            "parts": {
                "quiz_completeness": quiz_completeness,
                "history_reliability": history_reliability,
                "agreement": agreement,
            },
            "history_quiz_gap": gap,
        },
        "warnings": warnings,
    }


PILLAR_TEXT = {
    "quiz": {"key": "quiz", "title": "Quiz", "your": "votre quiz", "answers": "vos réponses au quiz"},
    "situations": {"key": "situations", "title": "Mises en situation", "your": "vos mises en situation",
                   "answers": "vos choix en mise en situation"},
}


def second_pillar(profile: dict) -> dict:
    """Clé et libellés du second pilier du profil : « quiz » (v1) ou « situations » (v2)."""
    version = profile.get("model", {}).get("version", "v1")
    return PILLAR_TEXT["situations" if version == "v2" else "quiz"]


def history_reliability_v2(history: history_score.HistoryResult) -> float:
    """Nombre de transactions x couverture des indicateurs x ancienneté (un historique de quelques jours vaut moins)."""
    if history.score is None:
        return 0.0
    span = min(1.0, history.span_days / config.HISTORY_SPAN_FULL_DAYS)
    span_factor = config.HISTORY_SPAN_MIN_FACTOR + (1.0 - config.HISTORY_SPAN_MIN_FACTOR) * span
    return min(1.0, history.n_trades / config.N_TRANSACTIONS_FULL) * history.coverage * span_factor


def combine_scores_v2(history: history_score.HistoryResult, sit: situations.SituationResult) -> dict:
    """Score v2 : poids de base 60/40 (historique/situations), ajustés par la fiabilité de chaque pilier."""
    h, s = history.score, sit.score
    if h is None and s is None:
        raise ValueError("Impossible de calculer un score : ni historique exploitable, ni mise en situation répondue.")
    rel_h, rel_s = history_reliability_v2(history), sit.reliability

    if s is None:
        w_h, w_s = 1.0, 0.0
    elif h is None:
        w_h, w_s = 0.0, 1.0
    else:
        base = config.HISTORY_WEIGHT_BASE_V2
        denom = base * rel_h + (1.0 - base) * rel_s
        w_h = base if denom <= 0 else base * rel_h / denom
        w_s = 1.0 - w_h
    history_part = 0.0 if h is None else w_h * h
    sit_part = 0.0 if s is None else w_s * s
    final = history_part + sit_part

    gap = abs(h - s) if (h is not None and s is not None) else None
    agreement = 0.0 if gap is None else 1.0 - min(1.0, gap / config.AGREEMENT_GAP_MAX)
    cw = config.CONFIDENCE_WEIGHTS_V2
    confidence = cw["situations"] * rel_s + cw["history"] * rel_h + cw["agreement"] * agreement

    margin = config.VERDICT_MAX_UNCERTAINTY_MARGIN * (1.0 - confidence)
    if gap is not None:
        margin += config.TOLERANCE_MARGIN_GAP_COEF * max(0.0, gap - config.TOLERANCE_MARGIN_GAP_FREE)

    warnings: list[str] = []
    if gap is not None and gap >= config.DIVERGENCE_WARNING_GAP:
        direction = "plus tolérant" if s > h else "plus prudent"
        warnings.append(f"Écart notable entre l'historique ({h:.0f}) et les mises en situation ({s:.0f}) : "
                        f"l'utilisateur se montre {direction} en scénario que dans son comportement passé.")

    return {
        "final_score": final,
        "final_score_display": round(final, config.SCORE_DISPLAY_DECIMALS),
        "components": {
            "history": {"score": h, "effective_weight": w_h, "contribution": history_part},
            "situations": {"score": s, "effective_weight": w_s, "contribution": sit_part},
        },
        "confidence": {
            "value": confidence,
            "label": confidence_label(confidence),
            "parts": {"situations_reliability": rel_s, "history_reliability": rel_h, "agreement": agreement},
            "history_situations_gap": gap,
        },
        "uncertainty": {"margin": margin, "low": max(0.0, final - margin), "high": min(100.0, final + margin)},
        "warnings": warnings,
    }


def round_floats(obj, decimals: int):
    if isinstance(obj, float):
        return round(obj, decimals)
    if isinstance(obj, dict):
        return {k: round_floats(v, decimals) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, decimals) for v in obj]
    return obj


def compute_user_profile(
    user_id: str,
    as_of: date,
    transactions: list[Transaction],
    quiz_answers: dict[str, int] | None = None,
    declared: dict | None = None,
    situations_answers: list[dict] | None = None,
    model_version: str | None = None,
) -> dict:
    """Profil complet, sérialisable en JSON, avec le détail du calcul.

    `declared` (horizon, préférences, exclusions...) est conservé tel quel mais
    N'ENTRE PAS dans le score : il est réservé à la future couche de gouvernance.
    """
    version = model_version or config.SCORE_MODEL_VERSION
    if version not in ("v1", "v2"):
        raise ValueError(f"Version de modèle inconnue : {version!r}.")
    if version == "v2":
        return _compute_user_profile_v2(user_id, as_of, transactions, situations_answers, declared)
    quiz_answers = quiz_answers or {}
    trades, tx_warnings = validate_and_sort(transactions, as_of)
    history = history_score.compute_history_score(trades, as_of)
    quiz_result = quiz.score_quiz(quiz_answers)
    combined = combine_scores(history, quiz_result)

    profile = {
        "user_id": user_id,
        "as_of": as_of.isoformat(),
        "model": {"version": "v1"},
        "config": {"version": config.CONFIG_VERSION, "fingerprint": config.fingerprint()},
        "inputs": {
            "transactions": [t.to_dict() for t in sorted(
                transactions, key=lambda t: (t.date, t.ticker, t.side, t.quantity))],
            "quiz_answers": {k: quiz_answers[k] for k in sorted(quiz_answers)},
            "declared_not_scored": declared or {},
        },
        "history": {
            "score": history.score,
            "coverage": history.coverage,
            "n_valid_trades": history.n_trades,
            "indicators": [asdict(i) for i in history.indicators],
        },
        "quiz": {
            "score": quiz_result.score,
            "n_answered": quiz_result.n_answered,
            "n_questions": quiz_result.n_questions,
            "items": quiz_result.items,
        },
        "final_score": combined["final_score"],
        "final_score_display": combined["final_score_display"],
        "components": combined["components"],
        "confidence": combined["confidence"],
        "warnings": tx_warnings + history.warnings + quiz_result.warnings + combined["warnings"],
    }
    return round_floats(profile, config.JSON_DECIMALS)


def _compute_user_profile_v2(user_id: str, as_of: date, transactions: list[Transaction],
                             situations_answers: list[dict] | None, declared: dict | None) -> dict:
    trades, tx_warnings = validate_and_sort(transactions, as_of)
    history = history_v2.compute_history_score(trades, as_of)
    sit = situations.score_situations(situations_answers)
    combined = combine_scores_v2(history, sit)
    profile = {
        "user_id": user_id,
        "as_of": as_of.isoformat(),
        "model": {"version": "v2"},
        "config": {"version": config.CONFIG_VERSION, "fingerprint": config.fingerprint()},
        "inputs": {
            "transactions": [t.to_dict() for t in sorted(
                transactions, key=lambda t: (t.date, t.ticker, t.side, t.quantity))],
            "situations": [dict(a) for a in (situations_answers or [])],
            "declared_not_scored": declared or {},
        },
        "history": {
            "score": history.score,
            "coverage": history.coverage,
            "n_valid_trades": history.n_trades,
            "span_days": history.span_days,
            "indicators": [asdict(i) for i in history.indicators],
        },
        "situations": {
            "score": sit.score,
            "n_answered": sit.n_answered,
            "n_questions": sit.n_questions,
            "consistency": sit.consistency,
            "reliability": sit.reliability,
            "items": sit.items,
        },
        "final_score": combined["final_score"],
        "final_score_display": combined["final_score_display"],
        "components": combined["components"],
        "confidence": combined["confidence"],
        "uncertainty": combined["uncertainty"],
        "warnings": tx_warnings + history.warnings + sit.warnings + combined["warnings"],
    }
    return round_floats(profile, config.JSON_DECIMALS)
