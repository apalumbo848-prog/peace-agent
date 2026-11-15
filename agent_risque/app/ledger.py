"""Registre des achats SIMULÉS (aucune transaction réelle, aucun argent).

Un fichier JSON par profil. Chaque achat simulé est converti en une `Transaction`
ordinaire (date = date de référence, prix = clôture lue dans les données) : le profil
se recalcule ensuite avec exactement les mêmes règles que pour l'historique de départ.
Le registre ne stocke ni horodatage ni nom : mêmes entrées = même fichier.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

from .. import config, data_access
from ..transactions import Transaction

_SAFE_ID = re.compile(r"^[a-z0-9_]{1,40}$")


class LedgerError(ValueError):
    """Achat simulé refusé (message lisible, en français)."""


def _path(user_id: str, directory: Path | None) -> Path:
    if not _SAFE_ID.match(user_id):                       # empêche tout chemin de fichier inattendu
        raise LedgerError("Identifiant de profil invalide.")
    return Path(directory or config.APP_DATA_DIR) / f"{user_id}_achats_simules.json"


def load(user_id: str, directory: Path | None = None) -> list[dict]:
    path = _path(user_id, directory)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)["purchases"]


def _write(path: Path, purchases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"purchases": purchases}, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")   # écriture atomique : fichier jamais à moitié écrit
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    os.replace(tmp, path)


def quote(ticker: str, amount_cad: float, as_of: date) -> dict:
    """Quantité et prix (CAD) d'un achat de `amount_cad` à la clôture de `as_of`. Refuse si impossible."""
    asset = data_access.get_asset(ticker)
    if asset is None:
        raise LedgerError("Titre absent des données.")
    if not (isinstance(amount_cad, (int, float)) and amount_cad == amount_cad and 0 < amount_cad <= config.APP_MAX_AMOUNT_CAD):
        raise LedgerError(f"Le montant doit être entre 0 et {config.APP_MAX_AMOUNT_CAD:,.0f} $ CAD.".replace(",", " "))
    bar = data_access.get_bar(ticker, as_of)
    if bar is None:
        raise LedgerError(f"Aucun prix de clôture pour {ticker} le {as_of} : achat simulé impossible.")
    price_cad = data_access.to_cad(bar.close, asset.currency, as_of)
    quantity = round(amount_cad / price_cad, 4)
    if quantity <= 0:
        raise LedgerError("Montant trop petit pour acheter une fraction de ce titre.")
    return {"date": as_of.isoformat(), "ticker": ticker, "side": "buy", "quantity": quantity,
            "price_cad": round(price_cad, 4), "amount_cad": round(quantity * price_cad, 2)}


def record_purchase(user_id: str, ticker: str, amount_cad: float, as_of: date,
                    directory: Path | None = None) -> dict:
    entry = quote(ticker, amount_cad, as_of)
    purchases = load(user_id, directory)
    if len(purchases) >= config.LEDGER_MAX_ENTRIES:
        raise LedgerError("Nombre maximal d'achats simulés atteint : réinitialisez le registre.")
    purchases.append(entry)
    _write(_path(user_id, directory), purchases)
    return entry


def reset(user_id: str, directory: Path | None = None) -> None:
    path = _path(user_id, directory)
    if path.exists():
        path.unlink()


def as_transactions(purchases: list[dict]) -> list[Transaction]:
    return [Transaction.from_dict({k: p[k] for k in ("date", "ticker", "side", "quantity")}) for p in purchases]
