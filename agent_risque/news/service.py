"""Chaîne Actualité d'une action : flux -> articles pertinents -> agent filtreur -> règles d'impact -> instantané.

Instantané : le résultat est enregistré par action et par jour (app_data/news/). Rouvrir la page le même jour
redonne EXACTEMENT le même verdict (répétable) ; « Actualiser » (refresh) relance toute la chaîne.
Une panne (réseau, AWS) donne le statut « indisponible » : le verdict est alors calculé sans actualité, et la page le dit.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .. import config, data_access
from . import agent as news_agent
from . import feeds, impact


def _snapshot_path(ticker: str, directory: Path | None, today: date) -> Path:
    base = (directory or config.APP_DATA_DIR) / "news"
    return base / f"{re.sub(r'[^A-Za-z0-9_-]', '_', ticker)}_{today.isoformat()}.json"


def _empty(status: str, **extra) -> dict:
    return {"status": status, "adjustment": 0.0, "extra_margin": 0.0, "groups": [], "events": [], "rejected": [],
            "read": [], "considered": [], "sources": {}, "retrieved_at": "", "error": None, **extra}


def get_news(ticker: str, directory: Path | None = None, refresh: bool = False, fetcher=None,
             agent_factory=None, today: date | None = None) -> dict:
    """Statuts : « ok » (analysé), « aucune » (aucun article pertinent), « indisponible » (panne)."""
    today = today or date.today()
    path = _snapshot_path(ticker, directory, today)
    if path.exists() and not refresh:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("status") == "ok":           # les règles d'impact sont fixes : on les réapplique aux événements déjà vérifiés
                saved.update(impact.assess(saved.get("events", [])))
            return saved
        except (OSError, ValueError):
            pass
    asset = data_access.get_asset(ticker)
    articles, sources = feeds.fetch_all(ticker, fetcher)
    if all(s != "ok" for s in sources.values()):
        return _empty("indisponible", sources=sources, error="aucune source n'a répondu")
    chosen = feeds.select(articles, ticker, asset.name)
    considered = [{"source": a.source_name, "orientation": a.orientation, "title": a.title,
                   "link": a.link, "published": a.published} for a in chosen]
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not chosen:
        result = _empty("aucune", sources=sources, retrieved_at=retrieved)
    else:
        feeds.load_full_text(chosen, fetcher)
        ctx = news_agent.NewsContext(ticker, asset.name, asset.sector, {a.id: a for a in chosen})
        outcome = news_agent.analyze(ctx, agent_factory)
        if outcome["error"]:
            return _empty("indisponible", sources=sources, considered=considered, error=outcome["error"])
        assessment = impact.assess(outcome["events"])
        result = {"status": "ok", **assessment, "events": outcome["events"], "rejected": outcome["rejected"],
                  "read": outcome["read"], "considered": considered, "sources": sources, "retrieved_at": retrieved,
                  "error": None}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return result
