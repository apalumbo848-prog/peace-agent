"""Règles FIXES qui transforment des événements VÉRIFIÉS en points de risque. Aucune IA ici.

- Seuls les événements qui augmentent le risque comptent (asymétrie prudente).
- Un événement ne compte que s'il est rapporté par au moins NEWS_MIN_SOURCES sources différentes ;
  sa gravité retenue est la plus basse déclarée (on ne retient pas l'emballement d'une seule source).
- Règle du nombre : même sans confirmation, beaucoup d'articles défavorables distincts (quelles que soient les sources)
  ajoutent quelques points (NEWS_VOLUME_POINTS). Les articles déjà comptés par une confirmation ne sont pas recomptés.
- Si les sources s'écartent beaucoup sur la gravité, le score ne bouge pas davantage : la marge d'incertitude
  du verdict s'élargit et la page le dit.
- Le total est plafonné à NEWS_MAX_POINTS.
"""

from __future__ import annotations

from .. import config


def assess(events: list[dict]) -> dict:
    """events : dicts avec type, severity, source_id, source_name, orientation (déjà vérifiés)."""
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    groups = []
    total = 0.0
    diverge = False
    for etype, evs in by_type.items():
        sources = sorted({e["source_id"] for e in evs})
        severities = [e["severity"] for e in evs]
        corroborated = len(sources) >= config.NEWS_MIN_SOURCES
        level = min(severities)
        spread = max(severities) - min(severities)
        diverges = corroborated and spread >= config.NEWS_DIVERGENCE_SPREAD
        points = config.NEWS_SEVERITY_POINTS[level] if corroborated else 0.0
        total += points
        diverge = diverge or diverges
        groups.append({
            "type": etype, "label": config.NEWS_EVENT_TYPES[etype], "corroborated": corroborated,
            "n_sources": len(sources), "orientations": sorted({e["orientation"] for e in evs}),
            "severity": level, "points": points, "diverges": diverges,
        })
    counted_types = {g["type"] for g in groups if g["corroborated"]}
    loose_links = {e.get("link") or f'{e["source_id"]}:{e["type"]}' for e in events if e["type"] not in counted_types}
    volume_points = next((pts for n, pts in config.NEWS_VOLUME_POINTS if len(loose_links) >= n), 0.0)
    total += volume_points
    adjustment = min(config.NEWS_MAX_POINTS, total)
    return {
        "adjustment": adjustment,
        "capped": total > config.NEWS_MAX_POINTS,
        "extra_margin": config.NEWS_DIVERGENCE_MARGIN if diverge else 0.0,
        "groups": groups,
        "n_events": len(events),
        "volume": {"n_articles": len(loose_links), "points": volume_points},
        "n_corroborated": sum(1 for g in groups if g["corroborated"]),
    }
