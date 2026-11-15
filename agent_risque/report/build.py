"""Assemble le rapport : fiche de faits, texte (fixe ou reformulé), vérification, trace.

Mode par défaut "template" : aucun appel externe. Le mode "llm" envoie la fiche de faits
(profils fictifs, aucun nom) à Amazon Bedrock, seulement quand on le demande.
"""

from __future__ import annotations

from .. import constraints
from ..asset_score import AssetRiskResult
from . import facts, llm_text, template_text, trace, verify


def build_report(verdict: dict, profile: dict, asset: AssetRiskResult, level: str | None = None,
                 mode: str = "template", client=None, cache_dir=None, use_cache: bool = True) -> dict:
    if mode not in ("template", "llm"):
        raise ValueError("mode doit être 'template' ou 'llm'.")
    if level is None:
        declared, _ = constraints.parse_declared(profile["inputs"].get("declared_not_scored"))
        level = declared.experience
    sheet = facts.build_fact_sheet(verdict, profile, asset, level)

    meta = {"mode": "template", "model_id": None, "attempts": 0, "cache_hit": False, "fallback_reason": None}
    report = None
    if mode == "llm":
        try:
            report, llm_meta = llm_text.generate_verified(sheet, client=client, cache_dir=cache_dir, use_cache=use_cache)
            meta.update(llm_meta)
        except llm_text.ReportGenerationError as exc:
            meta["fallback_reason"] = str(exc)[:300]
    if report is None:
        report = template_text.build_template_report(sheet)
        # La longueur n'est contrôlée que pour un texte généré : le texte fixe ne doit jamais bloquer la page.
        errors = verify.verify_report(report, sheet, check_total_length=False)
        if errors:                                        # le texte fixe doit toujours passer : sinon, c'est un bogue
            raise RuntimeError("Le texte fixe ne passe pas la vérification : " + "; ".join(errors[:5]))

    return {
        "level": level,
        "sheet": sheet,
        "report": report,
        "meta": meta,
        "trace": trace.build_trace(verdict, profile, asset, meta, level),
    }
