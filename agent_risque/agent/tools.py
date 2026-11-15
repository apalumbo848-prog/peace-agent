"""Outils en LECTURE SEULE que l'agent de suivi peut appeler (et réponses préparées).

Règles :
- un outil ne calcule jamais un score à sa façon : il relit la fiche de faits ou appelle
  `comparison.compare` (étape 3) ;
- chaque résultat d'outil devient un « fait » numéroté (F = fiche de l'étape 4,
  S = scénario, G = glossaire) que la réponse doit citer ;
- chaque appel est journalisé (`tool_log`) pour que la page montre ce que l'agent a consulté.
Ces fonctions n'importent pas Strands : elles sont testables seules.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .. import comparison, config
from ..asset_score import AssetRiskResult
from ..report.facts import Fact, FactSheet, fr


@dataclass
class FollowupContext:
    sheet: FactSheet
    verdict: dict
    profile: dict
    asset: AssetRiskResult
    amount_cad: float
    extra_facts: list[Fact] = field(default_factory=list)   # faits S# et G# créés pendant la question
    tool_log: list[dict] = field(default_factory=list)

    def all_facts(self) -> dict[str, Fact]:
        return {**self.sheet.by_id(), **{f.id: f for f in self.extra_facts}}

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}{sum(1 for f in self.extra_facts if f.id.startswith(prefix)) + 1}"


def _format(facts: list[Fact], level: str) -> str:
    return "\n".join(f"[{f.id}] {f.text_for(level)}" for f in facts) or "(aucun fait)"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().strip())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------- outils


def get_facts(ctx: FollowupContext, section: str) -> str:
    """Faits de la fiche pour une section (en_bref, pourquoi, profil, action, contraintes, limites)."""
    valid = [s for s, _ in config.REPORT_SECTION_TITLES]
    ctx.tool_log.append({"tool": "get_facts", "args": section})
    if section not in valid:
        return f"Section inconnue. Sections possibles : {', '.join(valid)}."
    idx = ctx.sheet.level_index()
    facts = [f for f in ctx.sheet.facts if f.section == section and f.min_level <= idx]
    return _format(sorted(facts, key=lambda f: (f.priority, f.id)), ctx.sheet.level)


def recompute_with_amount(ctx: FollowupContext, amount_cad: float) -> str:
    """Scénario : le verdict (étape 3, mêmes règles) si le montant de l'achat était différent."""
    ctx.tool_log.append({"tool": "recompute_with_amount", "args": f"{amount_cad}"})
    try:
        amount = float(amount_cad)
    except (TypeError, ValueError):
        return "Montant invalide."
    if not (0 < amount <= config.APP_MAX_AMOUNT_CAD):
        return f"Montant invalide : il doit être entre 0 et {config.APP_MAX_AMOUNT_CAD:,.0f} $ CAD.".replace(",", " ")
    verdict = comparison.compare(ctx.profile, ctx.asset, amount)
    new: list[Fact] = []

    def add(key: str, section: str, type_: str, text: str, source: str) -> None:
        fact = Fact(id=ctx._next_id("S"), key=key, section=section, type=type_, text=text, source=source)
        ctx.extra_facts.append(fact)            # ajouté tout de suite : l'identifiant suivant est donc différent
        new.append(fact)

    add("scenario", "action", "hypothese",
        f"Scénario hypothétique : avec un achat de {fr(amount)} $ CAD, le verdict serait {verdict['final_color']}.",
        "comparison.compare")
    for c in verdict["constraints"]:
        if c["status"] in ("attention", "violation"):
            add(f"scenario:{c['key']}", "contraintes", "calcul", f"Dans ce scénario : {c['message']}", "constraints")
    return _format(new, ctx.sheet.level)


def explain_term(ctx: FollowupContext, term: str) -> str:
    """Définition fixe d'un terme (volatilité, baisse maximale, risque de queue, tolérance, écart, confiance, ESG, FNB)."""
    ctx.tool_log.append({"tool": "explain_term", "args": term})
    wanted = _norm(term)
    for key, definition in config.FOLLOWUP_GLOSSARY.items():
        if _norm(key) == wanted or _norm(key) in wanted or wanted in _norm(key) and len(wanted) > 3:
            fact = Fact(id=ctx._next_id("G"), key=f"glossaire:{key}", section="limites", type="donnee",
                        text=definition, source="glossaire fixe")
            ctx.extra_facts.append(fact)
            return _format([fact], ctx.sheet.level)
    return f"Terme inconnu. Termes possibles : {', '.join(config.FOLLOWUP_GLOSSARY)}."


# ------------------------------------------------------------------ réponses préparées
# Sans IA : phrases = textes de faits existants, chacune citant son fait.


def _sentences(facts: list[Fact], level: str) -> list[dict]:
    return [{"text": f.text_for(level), "facts": [f.id]} for f in facts]


def preset_why_color(ctx: FollowupContext) -> list[dict]:
    selected = ctx.sheet.selected()
    return _sentences(selected["en_bref"] + selected["pourquoi"], ctx.sheet.level)


def preset_profile(ctx: FollowupContext) -> list[dict]:
    return _sentences(ctx.sheet.selected()["profil"], ctx.sheet.level)


def preset_scenario(ctx: FollowupContext, amount_cad: float) -> list[dict]:
    recompute_with_amount(ctx, amount_cad)
    return _sentences(ctx.extra_facts, ctx.sheet.level)
