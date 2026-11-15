"""Analyse de sensibilité du modèle v2 et comparaison v1 / v2.

    python -m agent_risque.analysis.sensibilite            # affiche et écrit docs/sensibilite_v2.md

Il n'existe pas de « vérité » (tolérance réelle connue) pour optimiser les poids statistiquement.
On vérifie donc leur ROBUSTESSE : chaque poids est modifié de +/-10 points (les autres sont
renormalisés), puis on compte combien de verdicts (3 profils x 31 actions = 93 couples) changent de
couleur de risque et de combien bouge la tolérance. Un poids dont une petite variation change
beaucoup de verdicts est un poids fragile, à justifier ou à adoucir.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from .. import asset_score, combine, comparison, config, data_access
from ..fixtures import personas

AS_OF = personas.AS_OF
DOCS = Path(__file__).resolve().parents[1] / "docs"


def _assets() -> dict:
    return {t: asset_score.score_asset(t, AS_OF) for t in sorted(data_access.load_universe())}


def _evaluate(assets: dict, version: str = "v2") -> dict:
    """{(persona, ticker): (couleur du risque, score de tolérance)}."""
    out = {}
    for name, args in personas.all_personas().items():
        p = combine.compute_user_profile(**args, model_version=version)
        tol = comparison._effective_tolerance(p["final_score"], p["confidence"]["value"], p.get("uncertainty", {}).get("margin"))
        for t, a in assets.items():
            out[(name, t)] = (comparison.color_for_gap(a.score - tol), p["final_score"])
    return out


def _renormalise(weights: dict, key: str, delta: float) -> dict:
    """Ajoute `delta` au poids `key`, retire la même somme aux autres proportionnellement (somme restée à 1)."""
    new = dict(weights)
    new[key] = min(1.0, max(0.0, weights[key] + delta))
    others = [k for k in weights if k != key]
    rest = sum(weights[k] for k in others)
    target = 1.0 - new[key]
    for k in others:
        new[k] = weights[k] * target / rest if rest > 0 else 0.0
    return new


@contextlib.contextmanager
def _patched(name: str, value):
    old = getattr(config, name)
    setattr(config, name, value)
    try:
        yield
    finally:
        setattr(config, name, old)


def _diff(base: dict, other: dict) -> tuple[int, float]:
    changed = sum(1 for k in base if base[k][0] != other[k][0])
    shifts = {k[0]: abs(base[k][1] - other[k][1]) for k in base}             # écart du score par profil
    return changed, max(shifts.values())


def run() -> str:
    assets = _assets()
    base = _evaluate(assets)
    rows: list[tuple[str, int, float]] = []

    for key in config.HISTORY_V2_WEIGHTS:
        for delta in (-0.10, 0.10):
            with _patched("HISTORY_V2_WEIGHTS", _renormalise(config.HISTORY_V2_WEIGHTS, key, delta)):
                rows.append((f"poids de « {key} » {delta:+.2f}", *_diff(base, _evaluate(assets))))
    for delta in (-0.10, 0.10):
        with _patched("HISTORY_WEIGHT_BASE_V2", config.HISTORY_WEIGHT_BASE_V2 + delta):
            rows.append((f"poids de base historique {delta:+.2f} (60 % -> {100 * (0.6 + delta):.0f} %)", *_diff(base, _evaluate(assets))))
    for key in config.SITUATION_PART_WEIGHTS:
        for delta in (-0.10, 0.10):
            with _patched("SITUATION_PART_WEIGHTS", _renormalise(config.SITUATION_PART_WEIGHTS, key, delta)):
                rows.append((f"situations : poids de « {key} » {delta:+.2f}", *_diff(base, _evaluate(assets))))
    for hl in (365, 1095):
        with _patched("RECENCY_HALF_LIFE_DAYS", hl):
            rows.append((f"demi-vie de fraîcheur {hl} jours (base 730)", *_diff(base, _evaluate(assets))))

    total = len(base)
    lines = ["# Sensibilité du modèle v2", "",
             f"Chaque ligne modifie UN réglage ; on compte les verdicts de risque qui changent de couleur sur {total} couples "
             "(3 profils fictifs x 31 actions) et le plus grand déplacement de tolérance (points sur 100).", "",
             "| Variation | Verdicts changés | Déplacement max de la tolérance |", "|---|---|---|"]
    for label, changed, shift in rows:
        lines.append(f"| {label} | {changed} / {total} ({100 * changed / total:.0f} %) | {shift:.1f} |")
    worst = max(rows, key=lambda r: r[1])
    mean_changed = sum(r[1] for r in rows) / len(rows)
    lines += ["", f"Moyenne : {mean_changed:.1f} verdict(s) changé(s) par variation ({100 * mean_changed / total:.1f} %). "
              f"Variation la plus influente : {worst[0]} ({worst[1]} changements).", ""]

    # v1 contre v2 : tolérance et répartition des couleurs.
    v1, v2 = _evaluate(assets, "v1"), _evaluate(assets, "v2")
    lines += ["# Comparaison v1 et v2", "", "| Profil | Tolérance v1 | Tolérance v2 | Vert v1 / v2 | Jaune v1 / v2 | Rouge v1 / v2 |", "|---|---|---|---|---|---|"]
    for name in personas.all_personas():
        def count(ev, color):
            return sum(1 for (n, _), (c, _) in ev.items() if n == name and c == color)
        lines.append(f"| {name} | {v1[(name, 'SPY')][1]:.1f} | {v2[(name, 'SPY')][1]:.1f} | "
                     f"{count(v1, 'vert')} / {count(v2, 'vert')} | {count(v1, 'jaune')} / {count(v2, 'jaune')} | "
                     f"{count(v1, 'rouge')} / {count(v2, 'rouge')} |")
    text = "\n".join(lines) + "\n"
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "sensibilite_v2.md").write_text(text, encoding="utf-8", newline="\n")
    return text


if __name__ == "__main__":
    print(run())
