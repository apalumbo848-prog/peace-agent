"""Profils FICTIFS pour les tests et les démonstrations (aucune donnée personnelle).

Quatre profils inspirés des personas du défi : Amira (risque élevé), Mateo (risque modéré, ESG), Robert (risque faible
à modéré, achat impulsif) et Léa (aucun historique). Les historiques sont FIXES, enregistrés en JSON dans
fixtures/profiles/ (générés une fois par build_profiles.py, sans hasard) : mêmes fichiers = mêmes scores.
Chaque transaction contient date, titre, sens, quantité et prix de clôture réel du jour (le prix est une information
d'affichage ; les calculs relisent les prix des données).
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from .. import config
from ..transactions import Transaction

AS_OF = date(2026, 11, 12)   # dernier jour du jeu de données
PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
ORDER = ("amira", "mateo", "robert", "lea")


def _resp(ticker: str, ladder_accepted: int, reaction: int, tradeoff_accepted: int) -> dict:
    """Réponse fictive à une mise en situation : paliers acceptés depuis le plus bas, réaction (0-3), issues acceptées (0-3)."""
    max_loss = 10 * ladder_accepted                 # 0..5 = ancienne échelle de 10 %, convertie vers les paliers actuels
    return {"ticker": ticker, "ladder": [lv <= max_loss for lv in config.SITUATION_LADDER_LEVELS], "reaction": reaction,
            "tradeoff": [i < tradeoff_accepted for i in range(3)]}


@lru_cache(maxsize=None)
def _load(key: str) -> dict:
    return json.loads((PROFILES_DIR / f"{key}.json").read_text(encoding="utf-8"))


def label(key: str) -> str:
    return _load(key)["name"]


def description(key: str) -> str:
    d = _load(key)["declared"]
    return f"{d['age']} ans · {d['objective']}"


def all_personas() -> dict[str, dict]:
    """Dictionnaire clé -> arguments de combine.compute_user_profile."""
    out = {}
    for key in ORDER:
        data = _load(key)
        out[key] = {
            "user_id": data["user_id"],
            "as_of": AS_OF,
            "transactions": [Transaction.from_dict(t) for t in data["transactions"]],
            "quiz_answers": dict(data["quiz_answers"]),
            "situations_answers": [dict(r) for r in data["situations_answers"]],
            "declared": json.loads(json.dumps(data["declared"])),
        }
    return out

