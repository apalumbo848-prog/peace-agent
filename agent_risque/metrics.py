"""Mesures financières réutilisables (étape 1 et étape 2).

Volatilité annualisée = écart-type (échantillon) des rendements logarithmiques
journaliers de adj_close, multiplié par racine(jours d'annualisation).
Référence usuelle : Hull, Options, Futures and Other Derivatives.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from . import config, data_access


def annualization_days(asset_class: str) -> int:
    return config.ANNUALIZATION_DAYS.get(asset_class, config.ANNUALIZATION_DAYS["default"])


def annualized_vol_pct(adj_closes: list[float], asset_class: str) -> float | None:
    """Volatilité annualisée en %, ou None s'il y a moins de 2 rendements."""
    returns = [math.log(b / a) for a, b in zip(adj_closes, adj_closes[1:]) if a > 0 and b > 0]
    n = len(returns)
    if n < 2:
        return None
    mean = math.fsum(returns) / n
    variance = math.fsum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(variance) * math.sqrt(annualization_days(asset_class)) * 100.0


def trailing_vol_pct(ticker: str, end: date, include_end: bool) -> float | None:
    """Volatilité (%) sur les VOL_WINDOW_DAYS jours calendaires se terminant à `end`.

    include_end=False : fenêtre strictement avant `end` (volatilité connue au
    moment d'une transaction). include_end=True : jusqu'à `end` inclus (as_of).
    Renvoie None si moins de VOL_MIN_OBS rendements : on ne suppose rien.
    """
    asset = data_access.get_asset(ticker)
    if asset is None:
        return None
    start = end - timedelta(days=config.VOL_WINDOW_DAYS)
    bars = data_access.get_prices(ticker, start, end)
    if not include_end:
        bars = [b for b in bars if b.date < end]
    if len(bars) - 1 < config.VOL_MIN_OBS:
        return None
    return annualized_vol_pct([b.adj_close for b in bars], asset.asset_class)


def max_drawdown_pct(adj_closes: list[float]) -> float:
    """Baisse maximale (sommet -> creux) en % positif. 0 si la série ne baisse jamais."""
    peak = adj_closes[0]
    worst = 0.0
    for x in adj_closes:
        peak = max(peak, x)
        worst = max(worst, 1.0 - x / peak)
    return worst * 100.0


def current_drawdown_pct(adj_closes: list[float], lookback_rows: int) -> float:
    """Écart actuel (%) sous le plus haut des `lookback_rows` dernières séances."""
    recent_high = max(adj_closes[-lookback_rows:])
    return max(0.0, 1.0 - adj_closes[-1] / recent_high) * 100.0


def cvar_pct(adj_closes: list[float], quantile: float) -> float | None:
    """Perte moyenne (%, positive) des `quantile` pires rendements logarithmiques journaliers.

    CVaR / Expected Shortfall historique (Rockafellar et Uryasev, 2000 ; Acerbi et Tasche, 2002).
    """
    returns = sorted(math.log(b / a) for a, b in zip(adj_closes, adj_closes[1:]) if a > 0 and b > 0)
    if not returns:
        return None
    k = max(1, int(quantile * len(returns)))
    return -math.fsum(returns[:k]) / k * 100.0


def interpolate(x: float, anchors: tuple[tuple[float, float], ...]) -> float:
    """Interpolation linéaire par morceaux ; plat au-delà des extrémités."""
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise ValueError("Barème invalide : ancrages non croissants.")  # pragma: no cover


def vol_to_points(vol_pct: float) -> float:
    """Barème commun volatilité -> points 0-100 (aussi utilisé à l'étape 2)."""
    return interpolate(vol_pct, config.VOL_ANCHORS)
