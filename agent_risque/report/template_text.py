"""Rapport texte fixe : déterministe, sans IA, construit uniquement à partir des faits.

C'est le repli du rapport reformulé par un modèle, et la référence que le
vérificateur doit toujours accepter.
"""

from __future__ import annotations

from .. import config
from .facts import FactSheet


def build_template_report(sheet: FactSheet) -> dict:
    selected = sheet.selected()
    sections = []
    for section_id, title in config.REPORT_SECTION_TITLES:
        sentences = [
            {"text": fact.text_for(sheet.level), "facts": [fact.id]}
            for fact in selected[section_id]
        ]
        sections.append({"id": section_id, "title": title, "sentences": sentences})
    return {"sections": sections}
