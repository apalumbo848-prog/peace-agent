"""Taux USD/CAD du jour (Banque du Canada, API Valet, sans clé). Outil en lecture seule, sans IA.

Le taux sert à CONVERTIR un montant (information affichée) : il ne modifie pas le score de risque, car
le jeu de données mesure déjà chaque titre dans sa devise de cotation. Le taux est relu au plus une fois par heure.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, datetime, timezone

from . import config, data_access

_CACHE: dict = {"at": 0.0, "value": None}


def _fetch() -> dict:
    request = urllib.request.Request(config.FX_URL, headers={"User-Agent": config.NEWS_USER_AGENT})
    with urllib.request.urlopen(request, timeout=config.NEWS_FETCH_TIMEOUT_S) as response:       # noqa: S310
        data = json.loads(response.read(200_000))
    obs = data["observations"][-1]
    return {"rate": float(obs["FXUSDCAD"]["v"]), "date": obs["d"]}


def latest_usdcad(fetcher=None, now=time.time) -> dict | None:
    """{"rate", "date", "source", "retrieved_at"} ou None si la source ne répond pas."""
    if _CACHE["value"] and now() - _CACHE["at"] < config.FX_CACHE_SECONDS and fetcher is None:
        return _CACHE["value"]
    try:
        got = (fetcher or _fetch)()
        value = {**got, "source": "Banque du Canada (API Valet)",
                 "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    except Exception:
        return None
    if fetcher is None:
        _CACHE.update({"at": now(), "value": value})
    return value


def summary(amount_cad: float, as_of: date, fetcher=None) -> dict | None:
    """Taux du jour, taux des données à la date de référence, écart, et le montant converti en USD."""
    live = latest_usdcad(fetcher)
    if not live:
        return None
    ref = data_access.get_usdcad(as_of)
    change = (live["rate"] / ref - 1.0) * 100.0 if ref else None
    return {**live, "reference_rate": ref, "reference_date": as_of.isoformat(), "change_pct": change,
            "amount_usd": amount_cad / live["rate"]}
