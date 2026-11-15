"""Registre des réponses aux mises en situation (fictives), un fichier JSON par profil.

Une entrée = une action pour laquelle la personne a répondu OU a choisi « Passer » (pour ne pas
reposer la question). Les réponses sont validées par `situations.validate_response`. Même écriture
atomique et même absence d'horodatage que le registre d'achats : mêmes entrées = même fichier.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .. import config, situations
from .ledger import _SAFE_ID, LedgerError


def _path(user_id: str, directory: Path | None) -> Path:
    if not _SAFE_ID.match(user_id):
        raise LedgerError("Identifiant de profil invalide.")
    return Path(directory or config.APP_DATA_DIR) / f"{user_id}_mises_en_situation.json"


def load(user_id: str, directory: Path | None = None) -> list[dict]:
    path = _path(user_id, directory)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)["responses"]


def answered_tickers(user_id: str, directory: Path | None = None) -> set[str]:
    return {r["ticker"] for r in load(user_id, directory)}


def record(user_id: str, response: dict, directory: Path | None = None) -> dict:
    """Ajoute la réponse (ou le « Passer ») d'une action ; une action déjà traitée n'est pas rajoutée."""
    clean = situations.validate_response(response)         # lève ValueError si incomplète
    responses = load(user_id, directory)
    if clean["ticker"] in {r["ticker"] for r in responses}:
        raise LedgerError("Cette action a déjà reçu une réponse.")
    if len(responses) >= config.LEDGER_MAX_ENTRIES:
        raise LedgerError("Nombre maximal de réponses atteint : réinitialisez le registre.")
    responses.append(clean)
    path = _path(user_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"responses": responses}, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    os.replace(tmp, path)
    return clean


def reset(user_id: str, directory: Path | None = None) -> None:
    path = _path(user_id, directory)
    if path.exists():
        path.unlink()
