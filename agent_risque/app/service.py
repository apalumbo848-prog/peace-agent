"""Couche de service : relie profils, registre d'achats, score, verdict et rapport.

Aucune règle de calcul ici : tout est délégué aux modules des étapes 1 à 4. Cette couche
se contente d'ajouter les achats simulés à l'historique de départ du profil fictif, puis
d'appeler la chaîne habituelle. Elle est appelée seulement quand une page est demandée.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import asset_score, combine, comparison, data_access
from ..asset_score import AssetRiskResult
from ..fixtures import personas
from ..news import adjust
from ..report.build import build_report
from . import ledger, situation_ledger

PERSONA_LABELS = {k: personas.label(k) for k in personas.ORDER}
PERSONA_DESCRIPTIONS = {k: personas.description(k) for k in personas.ORDER}
AS_OF = personas.AS_OF


@dataclass
class Context:
    """Tout ce qu'une page d'action utilise, calculé une seule fois par requête."""
    persona: str
    profile: dict
    asset: AssetRiskResult
    verdict: dict
    amount_cad: float


def persona_keys() -> list[str]:
    return list(personas.all_personas())


def build_profile(persona: str, directory: Path | None = None) -> dict:
    """Profil = historique de départ + achats simulés du registre, recalculé de zéro."""
    args = dict(personas.all_personas()[persona])
    purchases = ledger.load(args["user_id"], directory)
    args["transactions"] = list(args["transactions"]) + ledger.as_transactions(purchases)
    # Réponses du profil fictif (avant la démo) + celles données dans les mises en situation de l'application.
    live = situation_ledger.load(args["user_id"], directory)
    args["situations_answers"] = list(args.get("situations_answers", [])) + live
    return combine.compute_user_profile(**args)


def needs_situation(persona: str, ticker: str, directory: Path | None = None) -> bool:
    """Vrai si la personne n'a encore ni répondu ni choisi « Passer » pour cette action."""
    return ticker not in situation_ledger.answered_tickers(user_id_of(persona), directory)


def user_id_of(persona: str) -> str:
    return personas.all_personas()[persona]["user_id"]


def open_asset_page(persona: str, ticker: str, amount_cad: float, directory: Path | None = None,
                    news: dict | None = None) -> Context:
    """L'agent démarre ICI, à l'ouverture de la page d'une action (jamais en arrière-plan).
    `news` : résultat de news.service.get_news (ajustement borné du score) ; None = actualité non utilisée."""
    profile = build_profile(persona, directory)
    asset = adjust.apply_news(asset_score.score_asset(ticker, AS_OF), news)
    verdict = comparison.compare(profile, asset, amount_cad)
    return Context(persona, profile, asset, verdict, amount_cad)


def report_for(ctx: Context, level: str | None = None, mode: str = "template", client=None, cache_dir=None) -> dict:
    return build_report(ctx.verdict, ctx.profile, ctx.asset, level=level, mode=mode, client=client, cache_dir=cache_dir)


def simulate_purchase(persona: str, ticker: str, amount_cad: float, directory: Path | None = None) -> dict:
    """Enregistre l'achat simulé et retourne le profil avant et après (pour montrer l'effet)."""
    before = build_profile(persona, directory)
    entry = ledger.record_purchase(user_id_of(persona), ticker, amount_cad, AS_OF, directory)
    after = build_profile(persona, directory)
    return {"entry": entry, "before": before, "after": after}


def universe_tickers() -> list[tuple[str, str, str]]:
    """(ticker, nom, classe) pour la liste d'accueil, triés par ticker."""
    return sorted((a.ticker, a.name, a.asset_class) for a in data_access.load_universe().values())
