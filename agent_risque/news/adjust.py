"""Applique l'effet de l'actualité sur le score d'une action (sans toucher à score_asset ni aux données de prix)."""

from __future__ import annotations

from dataclasses import replace

from ..asset_score import AssetRiskResult

_UNAVAILABLE = "Actualité récente indisponible"


def apply_news(asset: AssetRiskResult, news: dict | None) -> AssetRiskResult:
    """Retourne une copie de `asset` : score + ajustement borné, avertissements et champ `news` renseignés."""
    if not news:
        return asset
    base = asset.score
    warnings = [w for w in asset.warnings if not w.startswith(_UNAVAILABLE)]
    status = news.get("status")
    if status == "ok":
        adj = float(news["adjustment"])
        score = min(100.0, base + adj)
        if adj > 0:
            warnings.append(f"Actualité : le risque de l'action est relevé de {adj:.1f} point(s) à cause d'événements "
                            "confirmés par plusieurs sources ou nombreux articles défavorables.")
        else:
            warnings.append("Actualité récente analysée : aucun événement confirmé par plusieurs sources ne relève le risque.")
        extra = float(news["extra_margin"])
    else:
        adj, score, extra = 0.0, base, 0.0
        warnings.append("Actualité récente en cours d'analyse : le score ne repose pour l'instant que sur les prix historiques."
                        if status == "en_cours" else "Actualité récente indisponible : le score ne repose que sur les prix historiques."
                        if status != "aucune" else
                        "Aucun article récent trouvé sur cette action dans les sources suivies ; le score ne repose que sur les prix.")
    summary = {"status": status, "adjustment": adj, "extra_margin": extra, "base_score": base}
    return replace(asset, score=score, score_display=round(score, 1), warnings=warnings, news=summary)
