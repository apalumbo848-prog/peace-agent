"""Étape 2 : score de risque d'une action (0 = très stable, 100 = très risqué).

Appelé UNIQUEMENT quand l'utilisateur ouvre la page d'une action : fonction pure
score_asset(ticker, as_of), sans calcul en arrière-plan ni appel à un modèle d'IA.
Mêmes entrées = même score. Le score est décomposé en composantes (valeur brute,
points, poids, contribution), accompagné d'un indice de confiance, d'avertissements
et des sources de données. Les paramètres viennent de config.py.

Composantes : S1 volatilité, S2 baisse maximale, S3 risque de queue (CVaR 95 %),
S4 stress récent, S5 actualité (réservée : indisponible, aucune actualité dans les données).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from . import combine, config, data_access, metrics


class AssetScoreError(ValueError):
    """Aucun score ne peut être produit (titre inconnu ou historique insuffisant)."""


LABELS = {
    "volatility": "Volatilité",
    "drawdown": "Baisse maximale",
    "tail_risk": "Risque de queue (pires jours)",
    "recent_stress": "Stress récent",
    "news": "Actualité récente",
}


@dataclass
class AssetComponent:
    key: str
    label: str
    available: bool
    points: float | None = None         # 0-100
    raw_value: float | None = None
    raw_unit: str = ""
    base_weight: float = 0.0
    effective_weight: float = 0.0
    contribution: float = 0.0
    details: dict = field(default_factory=dict)
    note: str = ""


@dataclass
class AssetRiskResult:
    ticker: str
    name: str
    asset_class: str
    sector: str
    currency: str
    as_of: str
    window_start: str
    window_end: str
    n_returns: int
    score: float
    score_display: float
    components: list[AssetComponent]
    confidence: dict
    warnings: list[str]
    data_sources: list[dict]
    disclaimers: list[str]
    news: dict | None = None            # ajouté par news.adjust.apply_news ; None = actualité non utilisée

    def to_dict(self) -> dict:
        return combine.round_floats(asdict(self), config.JSON_DECIMALS)


def _component(key: str, points: float, raw: float, unit: str, details: dict | None = None) -> AssetComponent:
    return AssetComponent(key=key, label=LABELS[key], available=True, points=points,
                          raw_value=raw, raw_unit=unit,
                          base_weight=config.ASSET_COMPONENT_WEIGHTS[key], details=details or {})


def score_asset(ticker: str, as_of: date) -> AssetRiskResult:
    asset = data_access.get_asset(ticker)
    if asset is None:
        raise AssetScoreError(f"Titre inconnu : {ticker} n'est pas dans les données.")

    start = as_of - timedelta(days=config.ASSET_WINDOW_DAYS)
    bars = data_access.get_prices(ticker, start, as_of)
    n_returns = len(bars) - 1
    if n_returns < config.ASSET_MIN_RETURNS:
        raise AssetScoreError(
            f"Historique insuffisant pour {ticker} à la date {as_of} : {max(n_returns, 0)} rendements "
            f"disponibles, minimum {config.ASSET_MIN_RETURNS}. Aucun score n'est supposé.")

    adj = [b.adj_close for b in bars]
    warnings: list[str] = []

    # S1 - volatilité : fenêtre complète et 365 derniers jours.
    vol_window = metrics.annualized_vol_pct(adj, asset.asset_class)
    vol_recent = metrics.trailing_vol_pct(ticker, as_of, include_end=True)
    if vol_recent is None:
        blended = vol_window
        warnings.append("Volatilité récente non calculable (moins de 120 rendements sur 365 jours) : "
                        "seule la volatilité de la fenêtre est utilisée.")
    else:
        share = config.ASSET_VOL_RECENT_SHARE
        blended = (1.0 - share) * vol_window + share * vol_recent
    components = [
        _component("volatility", metrics.vol_to_points(blended), blended, "% volatilité annualisée (mélange)",
                   {"vol_window_pct": vol_window, "vol_recent_pct": vol_recent}),
    ]

    # S2 - baisse maximale.
    mdd = metrics.max_drawdown_pct(adj)
    components.append(_component("drawdown", metrics.interpolate(mdd, config.ASSET_DRAWDOWN_ANCHORS),
                                 mdd, "% baisse maximale sur la fenêtre"))

    # S3 - risque de queue.
    cvar = metrics.cvar_pct(adj, config.ASSET_TAIL_QUANTILE)
    components.append(_component("tail_risk", metrics.interpolate(cvar, config.ASSET_TAIL_ANCHORS),
                                 cvar, "% perte moyenne des 5 % pires jours"))

    # S4 - stress récent.
    stress = metrics.current_drawdown_pct(adj, config.ASSET_STRESS_LOOKBACK_ROWS)
    components.append(_component("recent_stress", metrics.interpolate(stress, config.ASSET_STRESS_ANCHORS),
                                 stress, "% sous le plus haut des 252 dernières séances"))

    # S5 - actualité : réservée, indisponible.
    components.append(AssetComponent(
        key="news", label=LABELS["news"], available=False,
        base_weight=config.ASSET_COMPONENT_WEIGHTS["news"],
        note="Aucune actualité dans les données fournies ; sera ajoutée avec des sources autorisées."))
    warnings.append("Actualité récente indisponible : le score ne repose que sur les prix historiques.")

    coverage = math.fsum(c.base_weight for c in components if c.available)
    for c in components:
        if c.available:
            c.effective_weight = c.base_weight / coverage
            c.contribution = c.effective_weight * c.points
    score = math.fsum(c.contribution for c in components)

    # Confiance.
    sufficiency = min(1.0, n_returns / config.ASSET_FULL_RETURNS)
    if vol_recent is None:
        stability = 0.0
        shift = None
    else:
        shift = abs(vol_recent - vol_window) / max(vol_window, config.ASSET_STABILITY_VOL_FLOOR)
        stability = 1.0 - min(1.0, shift)
    cw = config.ASSET_CONFIDENCE_WEIGHTS
    confidence = (cw["data_sufficiency"] * sufficiency + cw["coverage"] * coverage + cw["stability"] * stability)
    label = combine.confidence_label(confidence)
    news_missing = any(c.key == "news" and not c.available for c in components)
    if news_missing:
        label = combine.lowest_label(label, config.ASSET_LABEL_CAP_WITHOUT_NEWS)

    # Avertissements.
    if shift is not None and shift >= config.ASSET_REGIME_SHIFT_WARNING:
        warnings.append(f"Changement de régime : volatilité récente {vol_recent:.1f} % contre "
                        f"{vol_window:.1f} % sur la fenêtre ; le passé lointain décrit moins bien le présent.")
    if n_returns < config.ASSET_FULL_RETURNS:
        warnings.append(f"Historique plus court que prévu : {n_returns} rendements sur "
                        f"{config.ASSET_FULL_RETURNS} attendus.")
    if (as_of - bars[-1].date) > timedelta(days=config.STALE_PRICE_DAYS):
        warnings.append(f"Dernier prix disponible le {bars[-1].date} : données anciennes par rapport au {as_of}.")
    if asset.currency != "CAD":
        warnings.append(f"Prix en {asset.currency} : l'effet du taux de change n'est pas inclus dans le score.")
    if ticker in config.KNOWN_DATA_ISSUES:
        warnings.append(f"Anomalie connue des données : {config.KNOWN_DATA_ISSUES[ticker]}")

    sources = [s for s in (data_access.get_source_info("prices_daily.csv"),
                           data_access.get_source_info("assets_universe.csv")) if s]

    return AssetRiskResult(
        ticker=ticker, name=asset.name, asset_class=asset.asset_class, sector=asset.sector,
        currency=asset.currency, as_of=as_of.isoformat(),
        window_start=bars[0].date.isoformat(), window_end=bars[-1].date.isoformat(),
        n_returns=n_returns, score=score, score_display=round(score, config.SCORE_DISPLAY_DECIMALS),
        components=components,
        confidence={
            "value": confidence,
            "label": label,
            "label_capped_for_missing_news": news_missing,
            "parts": {"data_sufficiency": sufficiency, "coverage": coverage, "stability": stability},
        },
        warnings=warnings, data_sources=sources, disclaimers=list(config.ASSET_DISCLAIMERS),
    )
