"""Score de l'historique v2 (0-100) : ce que la personne a SUPPORTÉ plus que ce qu'elle détient.

Six indicateurs (poids : config.HISTORY_V2_WEIGHTS) :
  portfolio_vol       volatilité réelle du portefeuille, reconstituée jour par jour (la diversification compte)
  loss_endured        baisses du portefeuille (>= 10 % sous son plus haut) traversées sans vendre
  drop_reaction       réaction aux baisses de 10 % d'un titre détenu (mesure de la v1)
  risk_concentration  concentration du RISQUE : poids de chaque titre x sa volatilité (pas seulement sa valeur)
  risky_share         part de la valeur en actifs à forte volatilité (mesure de la v1)
  position_size       poids de la plus grosse position individuelle (mesure de la v1)

Fraîcheur : les observations passées pèsent moins (demi-vie config.RECENCY_HALF_LIFE_DAYS). Chaque
indicateur est un score 0-100 ou « indisponible » avec la raison ; rien n'est supposé. Même barème
commun que le risque d'une action (config.VOL_ANCHORS, config.ASSET_DRAWDOWN_ANCHORS). Déterministe.
"""

from __future__ import annotations

import math
from datetime import date

from . import config, data_access, history_score, metrics
from .history_score import HistoryResult, IndicatorResult
from .transactions import Trade

LABELS = {
    "portfolio_vol": "Volatilité réelle du portefeuille",
    "loss_endured": "Pertes traversées sans vendre",
    "drop_reaction": "Réaction aux baisses de 10 % ou plus",
    "risk_concentration": "Concentration du risque",
    "risky_share": "Part d'actifs risqués",
    "position_size": "Taille des positions",
}


def _decay(age_days: float) -> float:
    return 0.5 ** (max(0.0, age_days) / config.RECENCY_HALF_LIFE_DAYS)


def _unavailable(key: str, note: str) -> IndicatorResult:
    return IndicatorResult(key=key, label=LABELS[key], available=False,
                           base_weight=config.HISTORY_V2_WEIGHTS[key], note=note)


def _relabel(ind: IndicatorResult, key: str) -> IndicatorResult:
    ind.label = LABELS[key]
    ind.base_weight = config.HISTORY_V2_WEIGHTS[key]
    return ind


# --- série du portefeuille -------------------------------------------------

def portfolio_series(trades: list[Trade], as_of: date) -> list[dict]:
    """Valeur (CAD, prix de clôture), flux net et rendement quotidien du portefeuille.

    rendement = (valeur du jour - flux du jour) / valeur de la veille - 1 : un achat n'est pas un gain.
    L'indice `index` (base 1) enchaîne ces rendements et sert à mesurer les baisses.
    """
    if not trades:
        return []
    tickers = sorted({t.ticker for t in trades})
    start = min(t.date for t in trades)
    closes = {tk: {b.date: b.close for b in data_access.get_prices(tk, start, as_of)} for tk in tickers}
    by_date: dict[date, list[Trade]] = {}
    for t in trades:
        by_date.setdefault(t.date, []).append(t)
    dates = sorted(set().union(*[set(c) for c in closes.values()]) | set(by_date))
    assets = {tk: data_access.get_asset(tk) for tk in tickers}

    qty = {tk: 0.0 for tk in tickers}
    last: dict[str, float] = {}
    prev_value, index = 0.0, 1.0
    rows: list[dict] = []
    for d in dates:
        for tk in tickers:
            c = closes[tk].get(d)
            if c is not None:
                last[tk] = c
        flow = 0.0
        for t in by_date.get(d, []):
            qty[t.ticker] += t.signed_quantity
            flow += t.amount_cad if t.side == "buy" else -t.amount_cad
        value = math.fsum(data_access.to_cad(qty[tk] * last[tk], assets[tk].currency, d)
                          for tk in tickers if qty[tk] > 1e-9 and tk in last)
        ret = None
        if prev_value > 0:
            ret = (value - flow) / prev_value - 1.0
            if ret > -1.0:
                index *= 1.0 + ret
        rows.append({"date": d, "value": value, "flow": flow, "ret": ret, "index": index})
        prev_value = value
    return rows


# --- indicateurs -----------------------------------------------------------

def _portfolio_vol_indicator(series: list[dict], as_of: date) -> IndicatorResult:
    key = "portfolio_vol"
    obs = [(r["date"], math.log(1.0 + r["ret"])) for r in series if r["ret"] is not None and r["ret"] > -1.0]
    if len(obs) < config.PORTFOLIO_VOL_MIN_DAYS:
        return _unavailable(key, f"Moins de {config.PORTFOLIO_VOL_MIN_DAYS} jours de rendement de portefeuille observables.")
    w = [_decay((as_of - d).days) for d, _ in obs]
    total = math.fsum(w)
    mean = math.fsum(wi * r for wi, (_, r) in zip(w, obs)) / total
    var = math.fsum(wi * (r - mean) ** 2 for wi, (_, r) in zip(w, obs)) / total
    vol = math.sqrt(var) * math.sqrt(config.ANNUALIZATION_DAYS["default"]) * 100.0
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=metrics.vol_to_points(vol),
                           raw_value=vol, raw_unit="% de volatilité annualisée du portefeuille (fraîcheur pondérée)",
                           base_weight=config.HISTORY_V2_WEIGHTS[key], details={"days": len(obs)})


def _loss_episodes(series: list[dict], trades: list[Trade]) -> list[dict]:
    """Épisodes : du plus haut de l'indice jusqu'à son retour (ou la date de référence), profondeur >= seuil."""
    episodes: list[dict] = []
    peak_i = 0
    max_depth, max_depth_i = 0.0, 0

    def close(end_i: int, recovered: bool) -> None:
        if max_depth < config.LOSS_EPISODE_MIN_DEPTH:
            return
        start_d, end_d = series[peak_i]["date"], series[end_i]["date"]
        in_ep = [t for t in trades if start_d < t.date <= end_d]
        sold = math.fsum(t.amount_cad for t in in_ep if t.side == "sell")
        bought = math.fsum(t.amount_cad for t in in_ep if t.side == "buy")
        base_value = series[peak_i]["value"]
        net_sold = max(0.0, sold - bought) / base_value if base_value > 0 else 0.0
        first_sale = next((t for t in in_ep if t.side == "sell"), None)
        depth_at_sale = None
        if first_sale is not None:
            row = next(r for r in series if r["date"] == first_sale.date)
            depth_at_sale = max(0.0, 1.0 - row["index"] / series[peak_i]["index"])
        episodes.append({"start": start_d, "end": end_d, "recovered": recovered, "max_depth": max_depth,
                         "net_sold_fraction": net_sold, "depth_at_first_sale": depth_at_sale})

    for i, row in enumerate(series):
        if row["index"] >= series[peak_i]["index"]:
            close(i, True)
            peak_i, max_depth, max_depth_i = i, 0.0, i
            continue
        depth = 1.0 - row["index"] / series[peak_i]["index"]
        if depth > max_depth:
            max_depth, max_depth_i = depth, i
    close(len(series) - 1, False)
    return episodes


def _loss_endured_indicator(series: list[dict], trades: list[Trade], as_of: date) -> IndicatorResult:
    key = "loss_endured"
    episodes = _loss_episodes(series, trades) if series else []
    if not episodes:
        return _unavailable(key, "Aucune baisse du portefeuille de 10 % ou plus observée.")
    rows, weights, points = [], [], []
    for e in episodes:
        sold_out = e["net_sold_fraction"] > config.LOSS_SELL_TOLERANCE
        if sold_out and e["depth_at_first_sale"] is not None:
            pts = config.LOSS_SALE_FACTOR * metrics.interpolate(100.0 * e["depth_at_first_sale"], config.ASSET_DRAWDOWN_ANCHORS)
        else:
            pts = metrics.interpolate(100.0 * e["max_depth"], config.ASSET_DRAWDOWN_ANCHORS)
        weight = _decay((as_of - e["end"]).days)
        weights.append(weight)
        points.append(pts)
        rows.append({"start": e["start"].isoformat(), "end": e["end"].isoformat(), "max_depth_pct": 100.0 * e["max_depth"],
                     "sold_during": sold_out, "points": pts, "weight": weight})
    total = math.fsum(weights)
    score = math.fsum(w * p for w, p in zip(weights, points)) / total
    worst = max(e["max_depth"] for e in episodes)
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=score, raw_value=100.0 * worst,
                           raw_unit="% : plus forte baisse du portefeuille observée",
                           base_weight=config.HISTORY_V2_WEIGHTS[key], details={"episodes": rows})


def _drop_reaction_indicator(trades: list[Trade], as_of: date) -> IndicatorResult:
    key = "drop_reaction"
    by_ticker: dict[str, list[Trade]] = {}
    for t in trades:
        by_ticker.setdefault(t.ticker, []).append(t)
    events: list[dict] = []
    for ticker in sorted(by_ticker):
        events.extend(history_score._drop_events(ticker, by_ticker[ticker], as_of))
    if not events:
        return _unavailable(key, "Aucune baisse de 10 % ou plus pendant une période de détention observable.")
    weights = [_decay((as_of - date.fromisoformat(e["drop_date"])).days) for e in events]
    total = math.fsum(weights)
    score = math.fsum(w * e["points"] for w, e in zip(weights, events)) / total
    for w, e in zip(weights, events):
        e["weight"] = w / total
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=score,
                           raw_value=float(len(events)), raw_unit="événements de baisse observés",
                           base_weight=config.HISTORY_V2_WEIGHTS[key], details={"events": events})


def _risk_concentration_indicator(values: dict[str, float], as_of: date, warnings: list[str]) -> IndicatorResult:
    """Même formule que la concentration v1 (1/HHI), mais sur la part de RISQUE : valeur x volatilité."""
    key = "risk_concentration"
    risk: dict[str, float] = {}
    for ticker, value in sorted(values.items()):
        vol = metrics.trailing_vol_pct(ticker, as_of, include_end=True)
        if vol is None:
            warnings.append(f"Position {ticker} ignorée pour la concentration du risque : historique de prix insuffisant.")
            continue
        risk[ticker] = value * vol
    total = math.fsum(risk.values())
    if total <= 0:
        return _unavailable(key, "Aucune position avec un historique de prix suffisant.")
    hhi = 0.0
    for ticker, r in sorted(risk.items()):
        share = r / total
        asset = data_access.get_asset(ticker)
        factor = 1.0 / config.ETF_DIVERSIFICATION_FACTOR if asset.asset_class in config.DIVERSIFIED_ETF_CLASSES else 1.0
        hhi += share * share * factor
    n_eff = 1.0 / hhi
    score = 100.0 * max(0.0, min(1.0, (config.N_EFF_TARGET - n_eff) / (config.N_EFF_TARGET - 1)))
    top = max(risk, key=lambda k: (risk[k], k))
    return IndicatorResult(key=key, label=LABELS[key], available=True, score=score, raw_value=n_eff,
                           raw_unit="sources de risque effectives (1/HHI du risque)",
                           base_weight=config.HISTORY_V2_WEIGHTS[key],
                           details={"hhi": hhi, "top_risk_ticker": top, "top_risk_share": risk[top] / total})


# --- assemblage ------------------------------------------------------------

def compute_history_score(trades: list[Trade], as_of: date) -> HistoryResult:
    warnings: list[str] = []
    positions = history_score._positions(trades)
    values = history_score._value_positions(positions, as_of, warnings)
    series = portfolio_series(trades, as_of)

    indicators = [
        _portfolio_vol_indicator(series, as_of),
        _loss_endured_indicator(series, trades, as_of),
        _drop_reaction_indicator(trades, as_of),
        _risk_concentration_indicator(values, as_of, warnings),
        _relabel(history_score._risky_share_indicator(values, as_of, warnings), "risky_share"),
        _relabel(history_score._position_size_indicator(values), "position_size"),
    ]
    span_days = (as_of - min(t.date for t in trades)).days if trades else 0

    coverage = math.fsum(i.base_weight for i in indicators if i.available)
    for i in indicators:
        if not i.available:
            warnings.append(f"{i.label} : indisponible. {i.note}")
    if coverage <= 0:
        return HistoryResult(None, 0.0, len(trades), indicators, warnings, span_days)
    for i in indicators:
        if i.available:
            i.effective_weight = i.base_weight / coverage
            i.contribution = i.effective_weight * i.score
    score = math.fsum(i.contribution for i in indicators)
    return HistoryResult(score, coverage, len(trades), indicators, warnings, span_days)
