"""Seul module qui lit les données.

Pour remplacer les CSV par des sources en ligne, il suffit de réimplémenter les
fonctions publiques de ce fichier (même signatures, mêmes types de retour).
Aucune donnée n'est inventée : une donnée absente renvoie None ou lève une erreur.
"""

from __future__ import annotations

import bisect
import csv
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from . import config


@dataclass(frozen=True)
class Asset:
    ticker: str
    name: str
    asset_class: str
    market: str
    currency: str
    sector: str


@dataclass(frozen=True)
class PriceBar:
    date: date
    close: float       # ajusté pour les fractionnements seulement (valeur de marché)
    adj_close: float   # ajusté fractionnements + dividendes (rendements)


@lru_cache(maxsize=1)
def load_universe() -> dict[str, Asset]:
    path = config.DATA_DIR / "assets_universe.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return {
            row["ticker"]: Asset(
                ticker=row["ticker"],
                name=row["name"],
                asset_class=row["asset_class"],
                market=row["market"],
                currency=row["currency"],
                sector=row["sector"],
            )
            for row in csv.DictReader(f)
        }


def get_asset(ticker: str) -> Asset | None:
    return load_universe().get(ticker)


@lru_cache(maxsize=1)
def _load_prices() -> dict[str, tuple[tuple[date, ...], tuple[PriceBar, ...]]]:
    by_ticker: dict[str, list[PriceBar]] = {}
    path = config.DATA_DIR / "prices_daily.csv"
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bar = PriceBar(
                date=date.fromisoformat(row["date"]),
                close=float(row["close"]),
                adj_close=float(row["adj_close"]),
            )
            by_ticker.setdefault(row["ticker"], []).append(bar)
    result = {}
    for ticker, bars in by_ticker.items():
        bars.sort(key=lambda b: b.date)
        result[ticker] = (tuple(b.date for b in bars), tuple(bars))
    return result


def get_prices(ticker: str, start: date | None = None, end: date | None = None) -> list[PriceBar]:
    """Barres entre start et end inclus, triées par date. Liste vide si ticker inconnu."""
    entry = _load_prices().get(ticker)
    if entry is None:
        return []
    dates, bars = entry
    lo = 0 if start is None else bisect.bisect_left(dates, start)
    hi = len(bars) if end is None else bisect.bisect_right(dates, end)
    return list(bars[lo:hi])


def get_bar(ticker: str, d: date) -> PriceBar | None:
    """Barre exactement à la date d, sinon None."""
    entry = _load_prices().get(ticker)
    if entry is None:
        return None
    dates, bars = entry
    i = bisect.bisect_left(dates, d)
    if i < len(dates) and dates[i] == d:
        return bars[i]
    return None


def last_bar_on_or_before(ticker: str, d: date) -> PriceBar | None:
    entry = _load_prices().get(ticker)
    if entry is None:
        return None
    dates, bars = entry
    i = bisect.bisect_right(dates, d)
    return bars[i - 1] if i > 0 else None


def next_bar_on_or_after(ticker: str, d: date) -> PriceBar | None:
    entry = _load_prices().get(ticker)
    if entry is None:
        return None
    dates, bars = entry
    i = bisect.bisect_left(dates, d)
    return bars[i] if i < len(bars) else None


def get_source_info(filename: str) -> dict | None:
    """Source, date d'extraction, traitement et limites d'un fichier (sources_metadata.csv)."""
    path = config.DATA_DIR / "sources_metadata.csv"
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["file"] == filename:
                return {k: row[k] for k in
                        ("file", "source", "source_url", "retrieved_on", "coverage", "processing", "limitations")}
    return None


@lru_cache(maxsize=1)
def _load_fx() -> tuple[tuple[date, ...], tuple[float, ...]]:
    path = config.DATA_DIR / "fx_usdcad_daily.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append((date.fromisoformat(row["date"]), float(row["usdcad"])))
    rows.sort()
    return tuple(r[0] for r in rows), tuple(r[1] for r in rows)


def get_usdcad(d: date) -> float | None:
    """Taux USD/CAD à la date d ; reporte le dernier taux connu (jours fériés canadiens)."""
    dates, rates = _load_fx()
    i = bisect.bisect_right(dates, d)
    return rates[i - 1] if i > 0 else None


def to_cad(amount: float, currency: str, d: date) -> float:
    """Convertit un montant en CAD. Lève ValueError si le taux ou la devise manque."""
    if currency == "CAD":
        return amount
    if currency == "USD":
        rate = get_usdcad(d)
        if rate is None:
            raise ValueError(f"Aucun taux USD/CAD disponible à la date {d}.")
        return amount * rate
    raise ValueError(f"Devise non prise en charge : {currency}")
