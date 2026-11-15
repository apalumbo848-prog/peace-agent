"""Sauvegarde et lecture du profil en JSON.

Mise à jour = recalcul complet à partir des entrées (sans état caché). Seul
l'historique des scores passés est conservé d'une sauvegarde à l'autre ; il est
indexé par as_of (date explicite), jamais par l'heure d'écriture, pour que la
même entrée produise toujours exactement le même fichier.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _path_for(directory: Path, user_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", user_id)
    return Path(directory) / f"{safe}.json"


def dumps(profile: dict) -> str:
    """Sérialisation canonique (clés triées, indentation fixe)."""
    return json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def load_profile(directory: Path, user_id: str) -> dict | None:
    path = _path_for(directory, user_id)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_profile(profile: dict, directory: Path) -> Path:
    """Écrit le profil et fusionne l'historique des scores déjà enregistrés."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    previous = load_profile(directory, profile["user_id"])

    history = {}
    if previous:
        for entry in previous.get("score_history", []):
            history[entry["as_of"]] = entry
    history[profile["as_of"]] = {
        "as_of": profile["as_of"],
        "final_score": profile["final_score"],
        "confidence": profile["confidence"]["value"],
    }
    out = dict(profile)
    out["score_history"] = [history[k] for k in sorted(history)]

    path = _path_for(directory, profile["user_id"])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(out))
    return path
