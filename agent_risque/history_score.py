"""Score de l'historique de transactions (0-100), décomposé en 5 indicateurs.

I1 volatilité des titres achetés       I4 part d'actifs risqués
I2 concentration (nombre effectif)     I5 taille de la plus grosse position
I3 réaction aux baisses de 10 % ou plus

Chaque indicateur renvoie un score 0-100 ou "indisponible" (avec la raison) :
on ne suppose jamais une donnée absente. Déterministe : aucune aléa, aucun
appel à un modèle d'IA. Tous les paramètres viennent de config.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import config, data_access, metrics
from .transactions import Trade

LABELS = {
    "volatility": "Volatilité des titres achetés",
    "concentration": "Concentration du portefeuille",
    "drop_reaction": "Réaction aux baisses de 10 % ou plus",
    "risky_share": "Part d'actifs risqués",
    "position_size": "Taille des positions",
}


@dataclass
class IndicatorResult:
    key: str
    label: str
    available: bool
    score: float | None = None          # 0-100
    raw_value: float | None = None      # mesure brute (ex. volatilité en %)
    raw_unit: str = ""
    base_weight: float = 0.0
    effective_weight: float = 0.0       # après renormalisation si un indicateur manque
    contribution: float = 0.0           # effective_weight * score
    details: dict = field(default_factory=dict)
    note: str = ""


@dataclass
class HistoryResult:
    score: float | None
    coverage: float                     # somme des poids de base des indicateurs disponibles
    n_trades: int
    indicators: list[IndicatorResult]
    warnings: list[str]
    span_days: int = 0                  # ancienneté de l'historique (première transaction -> date de référence)


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _positions(trades: list[Trade]) -> dict[str, float]:
    qty: dict[str, float] = {}
    for t in trades:
        qty[t.ticker] = qty.get(t.ticker, 0.0) + t.signed_quantity
    return {k: v for k, v in sorted(qty.items()) if v > 1e-9}


def _value_positions(positions: dict[str, float], as_of: date, warnings: list[str]) -> dict[str, float]:
    """Valeur de marché en CAD de chaque position à as_of (dernier close connu)."""
    values: dict[str, float] = {}
    for ticker, qty in positions.items():
        asset = data_access.get_asset(ticker)
        bar = data_access.last_bar_on_or_before(ticker, as_of)
        if asset is None or bar is None:
            warnings.append(f"Position {ticker} non valorisée : aucun prix à la date {as_of}.")
            continue
        if (as_of - bar.date) > timedelta(days=config.STALE_PRICE_DAYS):
            warnings.append(f"Position {ticker} valorisée avec un prix du {bar.date} (plus de {config.STALE_PRICE_DAYS} jours).")
        values[ticker] = data_access.to_cad(qty * bar.close, asset.currency, bar.date)
    return values


def current_portfolio_values(trades: list[Trade], as_of: date) -> tuple[dict[str, float], list[str]]:
    """Valeur de marché en CAD de chaque position à as_of, et avertissements de valorisation."""
    warnings: list[str] = []
    return _value_positions(_positions(trades), as_of, warnings), warnings


def _unavailable(key: str, note: str) -> IndicatorResult:
    return IndicatorResult(key=key, label=LABELS[key], available=False,
                           base_weight=config.INDICATOR_WEIGHTS[key], note=note)


# --- I1 -------------------------------------------------------------------

def _volatility_indicator(trades: list[Trade], warnings: list[str]) -> IndicatorResult:
    key = "volatility"
    total = 0.0
    weighted = 0.0
    used = skipped = 0
    for t in trades:
        if t.side != "buy":
            continue
        vol = metrics.trailing_vol_pct(t.ticker, t.date, include_end=False)
        if vol is None:
            skipped += 1
            warnings.append(f"Achat {t.date} {t.ticker} ignoré pour la volatilité : historique de prix insuffisant avant la transaction.")
            continue
        total += t.amount_cad
        weighted += t.amount_cad * vol
        used += 1
    if used == 0:
        return _unavailable(key, "Aucun achat avec un historique de prix suffisant.")
    v = weighted / total
    return IndicatorResult(key=key, label=LABELS[key], available=True,
                           score=metrics.vol_to_points(v), raw_value=v, raw_unit="% volatilité annualisée pondérée",
                           base_weight=config.INDICATOR_WEIGHTS[key],
                           details={"purchases_used": used, "purchases_skipped": skipped})


# --- I2 -------------------------------------------------------------------

def _concentration_indicator(values: dict[str, float]) -> IndicatorResult:
    key = "concentration"
    total = math.fsum(values.values())
    if total <= 0:
        return _unavailable(key, "Aucune position valorisable à la date de référence.")
    hhi = 0.0
    for ticker, value in sorted(values.items()):
        w = value / total
        asset = data_access.get_asset(ticker)
        factor = (1.0 / config.ETF_DIVERSIFICATION_FACTOR
                  if asset.asset_class in config.DIVERSIFIED_ETF_CLASSES else 1.0)
        hhi += w * w * factor
    n_eff = 1.0 / hhi
    score = 100.0 * _clip((config.N_EFF_TARGET - n_eff) / (config.N_EFF_TARGET - 1), 0.0, 1.0)
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=score,
                           raw_value=n_eff, raw_unit="positions effectives (1/HHI)",
                           base_weight=config.INDICATOR_WEIGHTS[key],
                           details={"hhi": hhi, "n_positions": len(values)})


# --- I3 -------------------------------------------------------------------

def _reaction_points(net_change: float) -> float:
    for op, threshold, points in config.DROP_REACTION_RULES:
        if (op == ">=" and net_change >= threshold) or (op == ">" and net_change > threshold):
            return points
    return config.DROP_REACTION_DEFAULT_POINTS


def _drop_events(ticker: str, ticker_trades: list[Trade], as_of: date) -> list[dict]:
    bars = data_access.get_prices(ticker, end=as_of)
    n = len(bars)
    events: list[dict] = []
    next_allowed = 0
    for i in range(1, n):
        if i < next_allowed:
            continue
        lo = max(0, i - config.DROP_PEAK_LOOKBACK_ROWS)
        peak = max(b.adj_close for b in bars[lo:i])
        if bars[i].adj_close > (1.0 - config.DROP_THRESHOLD) * peak:
            continue
        held_before = math.fsum(t.signed_quantity for t in ticker_trades if t.date < bars[i].date)
        if held_before <= 1e-9:
            continue                      # titre non détenu : pas de réaction à mesurer
        end_i = i + config.DROP_REACTION_WINDOW_ROWS
        if end_i >= n:
            continue                      # fenêtre de réaction pas encore terminée à as_of
        window = [t for t in ticker_trades if bars[i].date <= t.date <= bars[end_i].date]
        net = math.fsum(t.signed_quantity for t in window) / held_before
        events.append({
            "ticker": ticker,
            "drop_date": bars[i].date.isoformat(),
            "net_change": net,
            "points": _reaction_points(net),
        })
        next_allowed = i + config.DROP_COOLDOWN_ROWS
    return events


def _drop_reaction_indicator(trades: list[Trade], as_of: date) -> IndicatorResult:
    key = "drop_reaction"
    by_ticker: dict[str, list[Trade]] = {}
    for t in trades:
        by_ticker.setdefault(t.ticker, []).append(t)
    events: list[dict] = []
    for ticker in sorted(by_ticker):
        events.extend(_drop_events(ticker, by_ticker[ticker], as_of))
    if not events:
        return _unavailable(key, "Aucune baisse de 10 % ou plus pendant une période de détention observable.")
    score = math.fsum(e["points"] for e in events) / len(events)
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=score,
                           raw_value=float(len(events)), raw_unit="événements de baisse observés",
                           base_weight=config.INDICATOR_WEIGHTS[key],
                           details={"events": events})


# --- I4 -------------------------------------------------------------------

def _bucket(vol_pct: float) -> str:
    if vol_pct < config.RISK_BUCKET_LOW_MAX:
        return "low"
    if vol_pct < config.RISK_BUCKET_HIGH_MIN:
        return "medium"
    return "high"


def _risky_share_indicator(values: dict[str, float], as_of: date, warnings: list[str]) -> IndicatorResult:
    key = "risky_share"
    weighted = total = 0.0
    shares = {"low": 0.0, "medium": 0.0, "high": 0.0}
    for ticker, value in sorted(values.items()):
        vol = metrics.trailing_vol_pct(ticker, as_of, include_end=True)
        if vol is None:
            warnings.append(f"Position {ticker} ignorée pour la part d'actifs risqués : historique de prix insuffisant.")
            continue
        bucket = _bucket(vol)
        weighted += value * config.RISK_BUCKET_POINTS[bucket]
        total += value
        shares[bucket] += value
    if total <= 0:
        return _unavailable(key, "Aucune position avec un historique de prix suffisant.")
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=weighted / total,
                           raw_value=100.0 * shares["high"] / total, raw_unit="% de la valeur en actifs à forte volatilité",
                           base_weight=config.INDICATOR_WEIGHTS[key],
                           details={"share_by_bucket": {k: v / total for k, v in shares.items()}})


# --- I5 -------------------------------------------------------------------

def _position_size_indicator(values: dict[str, float]) -> IndicatorResult:
    key = "position_size"
    total = math.fsum(values.values())
    if total <= 0:
        return _unavailable(key, "Aucune position valorisable à la date de référence.")
    top_ticker, top_weight = None, 0.0
    for ticker, value in sorted(values.items()):
        if data_access.get_asset(ticker).asset_class in config.SINGLE_NAME_CLASSES and value / total > top_weight:
            top_ticker, top_weight = ticker, value / total
    score = 100.0 * _clip(top_weight / config.SINGLE_NAME_MAX_WEIGHT, 0.0, 1.0)
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=score,
                           raw_value=100.0 * top_weight, raw_unit="% du portefeuille dans la plus grosse position individuelle",
                           base_weight=config.INDICATOR_WEIGHTS[key],
                           details={"top_ticker": top_ticker})


# --- Assemblage -----------------------------------------------------------

def compute_history_score(trades: list[Trade], as_of: date) -> HistoryResult:
    warnings: list[str] = []
    positions = _positions(trades)
    values = _value_positions(positions, as_of, warnings)

    indicators = [
        _volatility_indicator(trades, warnings),
        _concentration_indicator(values),
        _drop_reaction_indicator(trades, as_of),
        _risky_share_indicator(values, as_of, warnings),
        _position_size_indicator(values),
    ]

    coverage = math.fsum(i.base_weight for i in indicators if i.available)
    if coverage <= 0:
        for i in indicators:
            if not i.available:
                warnings.append(f"{i.label} : indisponible. {i.note}")
        return HistoryResult(None, 0.0, len(trades), indicators, warnings)

    for i in indicators:
        if i.available:
            i.effective_weight = i.base_weight / coverage
            i.contribution = i.effective_weight * i.score
        else:
            warnings.append(f"{i.label} : indisponible. {i.note}")
    score = math.fsum(i.contribution for i in indicators)
    return HistoryResult(score, coverage, len(trades), indicators, warnings)
