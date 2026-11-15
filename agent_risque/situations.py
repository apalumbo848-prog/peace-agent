"""Mises en situation (modèle v2) : le second pilier de la tolérance, à la place du quiz.

À la première ouverture d'une action, la personne répond à trois mini-scénarios fictifs :

  ladder   « Seriez-vous prêt à investir X $ si vous risquiez de perdre 10 %, 20 %... d'ici 2 ans ? »
           -> plus grande perte acceptée, convertie en points avec la MÊME table que la baisse maximale
              d'une action (config.ASSET_DRAWDOWN_ANCHORS) : tolérance et action sont dans la même unité.
  reaction « Six mois plus tard, la valeur a baissé de 20 %. Que faites-vous ? »  -> 0 / 33 / 67 / 100.
  tradeoff trois issues également probables (gain 2 fois plus grand que la perte) acceptées ou non
           -> 0 / 33 / 67 / 100 selon le nombre d'issues acceptées (mesure de l'aversion aux pertes).

Les paliers sont fixes (ne dépendent pas de l'action affichée) : aucune ancre venant du titre ne
déforme la mesure. Score d'une réponse = moyenne pondérée des trois parties ; score du pilier =
moyenne des dernières réponses, les plus récentes pesant plus. Les réponses contradictoires
(oui à -30 % mais non à -20 %) sont comptées et baissent la fiabilité. Déterministe, sans IA.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import config, metrics


@dataclass
class SituationResult:
    score: float | None                  # 0-100, None si aucune réponse exploitable
    n_answered: int                      # réponses retenues (les plus récentes, au plus SITUATION_MAX_KEPT)
    n_questions: int                     # nombre de réponses pour une fiabilité complète
    consistency: float = 1.0             # 0-1
    reliability: float = 0.0             # min(1, n / n_full) x cohérence
    items: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def scenario_texts(name: str, ticker: str, amount_cad: float) -> dict:
    """Textes affichés à la personne (aucun chiffre venant de l'action : seulement le montant prévu)."""
    amount = _fmt(amount_cad)
    years = config.SITUATION_HORIZON_YEARS
    drop = config.SITUATION_REACTION_DROP_PCT
    after = _fmt(amount_cad * (1 - drop / 100))
    return {
        "ladder": {
            "intro": f"Vous investissez {amount} $ CAD dans {name} ({ticker}). Pour chaque cas, dites si vous accepteriez de le faire.",
            "levels": [{"level": lv, "text": f"Je suis prêt à investir {amount} $ s'il y a un risque de perdre {lv} % d'ici {years} ans."}
                       for lv in config.SITUATION_LADDER_LEVELS],
        },
        "reaction": {
            "text": (f"Vous avez investi {amount} $. {config.SITUATION_REACTION_MONTHS} mois plus tard, la valeur a baissé de "
                     f"{drop} % : elle est de {after} $. Que faites-vous ?"),
            "options": [o for o, _ in config.SITUATION_REACTION_OPTIONS],
        },
        "tradeoff": {
            "intro": f"Pour {amount} $ investis, deux issues sont également probables d'ici {years} ans. Les acceptez-vous ?",
            "options": [{"gain": g, "loss": l,
                         "text": f"Une chance sur deux de gagner {g} % ({_fmt(amount_cad * g / 100)} $), une chance sur deux de perdre {l} % ({_fmt(amount_cad * l / 100)} $)."}
                        for g, l in config.SITUATION_TRADEOFFS],
        },
    }


def validate_response(raw: dict) -> dict:
    """Réponse normalisée ou ValueError. Une réponse « passée » (skipped) n'a pas de contenu."""
    if not isinstance(raw, dict) or not isinstance(raw.get("ticker"), str):
        raise ValueError("Réponse invalide : titre manquant.")
    if raw.get("skipped") is True:
        return {"ticker": raw["ticker"], "skipped": True}
    ladder, tradeoff, reaction = raw.get("ladder"), raw.get("tradeoff"), raw.get("reaction")
    if not (isinstance(ladder, list) and len(ladder) == len(config.SITUATION_LADDER_LEVELS)
            and all(isinstance(v, bool) for v in ladder)):
        raise ValueError("Réponse invalide : paliers de perte.")
    if not (isinstance(tradeoff, list) and len(tradeoff) == len(config.SITUATION_TRADEOFFS)
            and all(isinstance(v, bool) for v in tradeoff)):
        raise ValueError("Réponse invalide : issues à deux scénarios.")
    if not (isinstance(reaction, int) and not isinstance(reaction, bool)
            and 0 <= reaction < len(config.SITUATION_REACTION_OPTIONS)):
        raise ValueError("Réponse invalide : réaction à la baisse.")
    return {"ticker": raw["ticker"], "ladder": list(ladder), "reaction": reaction, "tradeoff": list(tradeoff)}


def _prefix_length(flags: list[bool]) -> tuple[int, bool]:
    """(nombre d'acceptations consécutives depuis le premier palier, cohérent ?)."""
    n = 0
    while n < len(flags) and flags[n]:
        n += 1
    return n, not any(flags[n:])


def score_response(resp: dict) -> dict:
    """Points de chaque partie et score d'une réponse (0-100). resp doit être validé."""
    n_ladder, ladder_ok = _prefix_length(resp["ladder"])
    max_loss = config.SITUATION_LADDER_LEVELS[n_ladder - 1] if n_ladder else 0
    ladder_points = metrics.interpolate(float(max_loss), config.SITUATION_LADDER_ANCHORS)
    reaction_points = config.SITUATION_REACTION_OPTIONS[resp["reaction"]][1]
    n_trade, trade_ok = _prefix_length(resp["tradeoff"])
    tradeoff_points = config.SITUATION_TRADEOFF_POINTS[n_trade]
    w = config.SITUATION_PART_WEIGHTS
    score = w["ladder"] * ladder_points + w["reaction"] * reaction_points + w["tradeoff"] * tradeoff_points
    return {"ticker": resp["ticker"], "max_accepted_loss_pct": max_loss, "ladder_points": ladder_points,
            "reaction_points": reaction_points, "tradeoff_points": tradeoff_points,
            "score": score, "consistent": ladder_ok and trade_ok}


def score_situations(responses: list[dict] | None) -> SituationResult:
    """Pilier « situations ». `responses` est dans l'ordre chronologique ; les réponses passées sont ignorées."""
    n_full = config.SITUATION_N_FULL
    warnings: list[str] = []
    valid: list[dict] = []
    for raw in responses or []:
        try:
            clean = validate_response(raw)
        except ValueError as exc:
            warnings.append(str(exc))
            continue
        if not clean.get("skipped"):
            valid.append(clean)
    valid = valid[-config.SITUATION_MAX_KEPT:]
    if not valid:
        return SituationResult(None, 0, n_full, 1.0, 0.0, [], warnings + ["Aucune mise en situation répondue."])

    scored = [score_response(r) for r in valid]
    n = len(scored)
    half = config.SITUATION_RECENCY_HALF_LIFE
    weights = [0.5 ** ((n - 1 - k) / half) for k in range(n)]           # la plus récente pèse 1
    total_w = math.fsum(weights)
    score = math.fsum(w * s["score"] for w, s in zip(weights, scored)) / total_w
    for w, s in zip(weights, scored):
        s["weight"] = w / total_w

    inconsistent_share = sum(1 for s in scored if not s["consistent"]) / n
    mean = score
    spread = math.sqrt(math.fsum(w * (s["score"] - mean) ** 2 for w, s in zip(weights, scored)) / total_w)
    consistency = max(0.0, 1.0 - config.SITUATION_INCONSISTENCY_PENALTY * inconsistent_share
                      - (1.0 - config.SITUATION_INCONSISTENCY_PENALTY) * min(1.0, spread / config.SITUATION_SPREAD_FULL))
    if inconsistent_share > 0:
        warnings.append(f"{sum(1 for s in scored if not s['consistent'])} réponse(s) contradictoire(s) : la fiabilité baisse.")
    reliability = min(1.0, n / n_full) * consistency
    return SituationResult(score, n, n_full, consistency, reliability, scored, warnings)
