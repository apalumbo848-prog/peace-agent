"""Transactions fictives : structure et validation.

Le prix n'est jamais fourni par l'utilisateur : il est lu dans les données à la
date de la transaction (close, devise de cotation), puis converti en CAD.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import data_access

VALID_SIDES = ("buy", "sell")


@dataclass(frozen=True)
class Transaction:
    date: date
    ticker: str
    side: str       # "buy" ou "sell"
    quantity: float

    @staticmethod
    def from_dict(d: dict) -> "Transaction":
        return Transaction(
            date=date.fromisoformat(d["date"]) if isinstance(d["date"], str) else d["date"],
            ticker=d["ticker"],
            side=d["side"],
            quantity=float(d["quantity"]),
        )

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "ticker": self.ticker,
            "side": self.side,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class Trade:
    """Transaction validée, enrichie du prix lu dans les données."""
    date: date
    ticker: str
    side: str
    quantity: float
    price: float        # close à la date, devise de cotation
    amount_cad: float   # quantity * price converti en CAD

    @property
    def signed_quantity(self) -> float:
        return self.quantity if self.side == "buy" else -self.quantity


def validate_and_sort(transactions: list[Transaction], as_of: date) -> tuple[list[Trade], list[str]]:
    """Retourne (trades valides triés, avertissements).

    Rejette, avec un message, toute transaction postérieure à as_of, sur un titre
    inconnu, sans prix à cette date, de quantité non positive, ou qui vendrait
    plus que la position détenue. Le tri rend le résultat indépendant de l'ordre
    d'entrée (déterminisme).
    """
    warnings: list[str] = []
    ordered = sorted(transactions, key=lambda t: (t.date, t.ticker, t.side, t.quantity))
    held: dict[str, float] = {}
    trades: list[Trade] = []

    for t in ordered:
        label = f"{t.date} {t.side} {t.quantity:g} {t.ticker}"
        asset = data_access.get_asset(t.ticker)
        if asset is None:
            warnings.append(f"Transaction rejetée ({label}) : titre absent des données.")
            continue
        if t.side not in VALID_SIDES:
            warnings.append(f"Transaction rejetée ({label}) : sens inconnu.")
            continue
        if not t.quantity > 0:
            warnings.append(f"Transaction rejetée ({label}) : quantité non positive.")
            continue
        if t.date > as_of:
            warnings.append(f"Transaction rejetée ({label}) : postérieure à la date de référence {as_of}.")
            continue
        bar = data_access.get_bar(t.ticker, t.date)
        if bar is None:
            warnings.append(f"Transaction rejetée ({label}) : aucun prix dans les données à cette date.")
            continue
        if t.side == "sell" and t.quantity > held.get(t.ticker, 0.0) + 1e-9:
            warnings.append(f"Transaction rejetée ({label}) : vente supérieure à la position détenue.")
            continue
        try:
            amount = data_access.to_cad(t.quantity * bar.close, asset.currency, t.date)
        except ValueError as exc:
            warnings.append(f"Transaction rejetée ({label}) : {exc}")
            continue
        held[t.ticker] = held.get(t.ticker, 0.0) + (t.quantity if t.side == "buy" else -t.quantity)
        trades.append(Trade(t.date, t.ticker, t.side, t.quantity, bar.close, amount))

    return trades, warnings
