"""Génère les 4 profils fictifs (Amira, Mateo, Robert, Léa) dans fixtures/profiles/*.json.

    python -m agent_risque.fixtures.build_profiles

Aucun hasard : les historiques ci-dessous sont écrits à la main ; seules les quantités sont calculées à partir
du prix de clôture RÉEL du jour (jeu de données) et du montant en CAD. Les dates sont alignées sur le prochain jour
de cotation du titre. Les JSON produits sont versionnés : les scores restent répétables sans relancer ce script.
Le jeu de données couvre 5 ans (2021-11-12 à 2026-11-12) : Mateo (6 ans demandés) et Robert (10 ans) sont donc ramenés à 5 ans.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .. import data_access
from ..transactions import Transaction
from .personas import AS_OF, _resp

OUT = Path(__file__).resolve().parent / "profiles"

# (date nominale, titre, "B" = achat d'un montant en CAD | "S" = vente d'une fraction de la position)
AMIRA = [
    ("2023-11-15", "NVDA", "B", 6000), ("2023-11-15", "SHOP.TO", "B", 5000), ("2023-11-15", "MSFT", "B", 5000),
    ("2023-11-15", "BTC-USD", "B", 3000), ("2023-11-15", "ETH-USD", "B", 2000), ("2023-11-15", "TSLA", "B", 2500),
    ("2024-01-22", "BTC-USD", "B", 1500), ("2024-01-25", "ETH-USD", "B", 1000),     # rachats pendant la baisse de janvier 2024
    ("2024-02-01", "BTC-USD", "B", 1000),
    ("2024-04-19", "NVDA", "B", 3000), ("2024-04-22", "TSLA", "B", 2000),
    ("2024-06-03", "MSFT", "B", 1500),
    ("2024-08-06", "SHOP.TO", "B", 3000), ("2024-08-07", "NVDA", "B", 2500), ("2024-08-07", "TSLA", "B", 1500),
    ("2024-09-06", "BTC-USD", "B", 2000),
    ("2024-10-01", "ETH-USD", "B", 1000),
    ("2024-12-18", "NVDA", "B", 1500),
    ("2025-01-09", "BTC-USD", "B", 1500), ("2025-01-14", "SHOP.TO", "B", 1500),
    ("2025-04-04", "NVDA", "B", 3000), ("2025-04-04", "SHOP.TO", "B", 2500),
    ("2025-04-08", "TSLA", "B", 2000), ("2025-04-08", "BTC-USD", "B", 2000), ("2025-04-08", "ETH-USD", "B", 1500),
    ("2025-04-08", "MSFT", "B", 2500), ("2025-04-08", "QQQ", "B", 3000),
    ("2025-06-02", "NVDA", "B", 1500),
    ("2025-10-30", "NVDA", "S", 0.15), ("2025-10-30", "SHOP.TO", "S", 0.10),         # petites prises de profit
    ("2026-02-02", "TSLA", "B", 1000),
    ("2026-03-30", "NVDA", "B", 2500), ("2026-05-13", "SHOP.TO", "B", 2500),
    ("2026-06-25", "MSFT", "B", 3000), ("2026-06-25", "ETH-USD", "B", 1500), ("2026-06-30", "BTC-USD", "B", 2500),
    ("2026-07-29", "TSLA", "B", 1500), ("2026-07-29", "NVDA", "B", 2000),
    ("2026-11-03", "SHOP.TO", "B", 1500), ("2026-11-10", "NVDA", "B", 2000),
]
MATEO = [
    ("2021-11-15", "ESGV", "B", 8000), ("2021-11-15", "XIU.TO", "B", 6000), ("2021-11-15", "RY.TO", "B", 4000),
    ("2021-11-15", "JNJ", "B", 3000), ("2021-11-15", "XOM", "B", 3000), ("2021-11-15", "CNQ.TO", "B", 3000),
    ("2021-11-15", "FTS.TO", "B", 3000), ("2021-11-15", "XBB.TO", "B", 3000),
    ("2022-05-02", "ESGV", "B", 1500), ("2022-11-01", "FTS.TO", "B", 1500),
    ("2023-05-01", "ESGV", "B", 1500), ("2023-11-01", "XIU.TO", "B", 1500),
    ("2024-04-10", "CNQ.TO", "S", 1.0),                    # vend ses titres pétroliers près de leur sommet, pas pendant une baisse
    ("2024-05-01", "ESGV", "B", 1500), ("2024-10-07", "XOM", "S", 1.0),
    ("2024-11-01", "FTS.TO", "B", 1500), ("2025-05-01", "ESGV", "B", 1500),
    ("2025-11-03", "XIU.TO", "B", 1500), ("2026-05-01", "ESGV", "B", 1500), ("2026-11-02", "FTS.TO", "B", 1500),
]
ROBERT = [
    ("2021-11-15", "ZST.TO", "B", 15000), ("2021-11-15", "XBB.TO", "B", 10000), ("2021-11-15", "RY.TO", "B", 8000),
    ("2021-11-15", "JNJ", "B", 6000), ("2021-11-15", "PG", "B", 5000), ("2021-11-15", "ENB.TO", "B", 5000),
    ("2023-10-04", "ENB.TO", "S", 1.0),                    # vend lors d'une forte baisse (creux d'octobre 2023)
    ("2024-12-17", "TSLA", "B", 3000),                     # achat impulsif d'un titre médiatisé, près de son sommet
    ("2025-02-14", "TSLA", "S", 1.0),                      # revendu à perte quelques semaines plus tard
    ("2025-03-03", "AGG", "B", 4000),
]

class _Builder:
    """Construit un historique chronologique ; les dates sont alignées sur le prochain jour de cotation du titre."""

    def __init__(self) -> None:
        self.transactions: list[Transaction] = []
        self.held: dict[str, float] = {}

    @staticmethod
    def _bar(nominal: str, ticker: str):
        bar = data_access.next_bar_on_or_after(ticker, date.fromisoformat(nominal))
        if bar is None:
            raise ValueError(f"Pas de prix pour {ticker} après {nominal}.")
        return bar

    def buy(self, nominal: str, ticker: str, amount_cad: float) -> None:
        bar = self._bar(nominal, ticker)
        price_cad = data_access.to_cad(bar.close, data_access.get_asset(ticker).currency, bar.date)
        qty = round(amount_cad / price_cad, 4)
        self.transactions.append(Transaction(bar.date, ticker, "buy", qty))
        self.held[ticker] = self.held.get(ticker, 0.0) + qty

    def sell(self, nominal: str, ticker: str, fraction: float) -> None:
        bar = self._bar(nominal, ticker)
        held = self.held.get(ticker, 0.0)
        qty = held if fraction >= 1.0 else round(held * fraction, 4)
        self.transactions.append(Transaction(bar.date, ticker, "sell", qty))
        self.held[ticker] = held - qty


# Quiz v1 (indices 0 à 3) et mises en situation v2 : réponses FICTIVES.

PROFILES = {
    "amira": {
        "name": "Amira", "age": 26, "horizon_years": [15, None], "objective": "Croissance à long terme",
        "preferences": ["technologie", "crypto"], "exclusions": {}, "experience": "intermediaire",
        "quiz": {"q1_chute": 3, "q2_gain_perte": 3, "q3_titre_mediatise": 2, "q4_part_volatile": 3, "q5_regret": 3},
        "situations": [_resp("NVDA", 5, 3, 3), _resp("TSLA", 5, 2, 3), _resp("BTC-USD", 4, 3, 3),
                       _resp("SHOP.TO", 5, 3, 2), _resp("AMZN", 5, 3, 3), _resp("ETH-USD", 4, 2, 3)],
        "history": AMIRA,
    },
    "mateo": {
        "name": "Mateo", "age": 41, "horizon_years": [8, 12], "objective": "Équilibre croissance-stabilité",
        "preferences": ["ESG"], "exclusions": {"sectors": ["Energy"]}, "experience": "intermediaire",
        "quiz": {"q1_chute": 2, "q2_gain_perte": 1, "q3_titre_mediatise": 1, "q4_part_volatile": 1, "q5_regret": 1},
        "situations": [_resp("SPY", 3, 1, 1), _resp("QQQ", 3, 2, 1), _resp("RY.TO", 3, 1, 2),
                       _resp("MSFT", 2, 1, 1), _resp("XIU.TO", 3, 2, 1), _resp("AAPL", 3, 1, 1)],
        "history": MATEO,
    },
    "robert": {
        "name": "Robert", "age": 59, "horizon_years": [3, 5], "objective": "Préservation du capital",
        "preferences": [], "exclusions": {}, "experience": "avance",
        "quiz": {"q1_chute": 1, "q2_gain_perte": 0, "q3_titre_mediatise": 0, "q4_part_volatile": 1, "q5_regret": 0},
        "situations": [_resp("XBB.TO", 1, 0, 0), _resp("RY.TO", 1, 0, 0), _resp("JNJ", 2, 1, 0),
                       _resp("SPY", 1, 0, 0), _resp("PG", 1, 1, 0), _resp("ZST.TO", 2, 0, 0)],
        "history": ROBERT,
    },
    "lea": {
        "name": "Léa", "age": 18, "horizon_years": [20, None], "objective": "Premier placement, petit montant",
        "preferences": [], "exclusions": {}, "experience": "debutant",
        "quiz": {"q1_chute": 2, "q2_gain_perte": 1, "q3_titre_mediatise": 1, "q4_part_volatile": 1, "q5_regret": 2},
        "situations": [_resp("SPY", 2, 1, 1), _resp("QQQ", 3, 2, 1), _resp("XIU.TO", 2, 2, 1)],
        "history": [],
    },
}


def build_one(key: str, spec: dict) -> dict:
    b = _Builder()
    txs = []
    for nominal, ticker, side, value in sorted(spec["history"], key=lambda r: r[0]):
        n = len(b.transactions)
        (b.buy if side == "B" else b.sell)(nominal, ticker, value)
        t = b.transactions[n]
        bar = data_access.get_prices(ticker, t.date, t.date)[0]
        txs.append({"date": t.date.isoformat(), "ticker": ticker, "side": "buy" if side == "B" else "sell",
                    "quantity": t.quantity, "price": round(bar.close, 4), "currency": data_access.get_asset(ticker).currency})
    declared = {"horizon_years": spec["horizon_years"], "preferences": spec["preferences"],
                "experience": spec["experience"], "age": spec["age"], "objective": spec["objective"]}
    if spec["exclusions"]:
        declared["exclusions"] = spec["exclusions"]
    return {"user_id": f"fictif_{key}", "name": spec["name"], "as_of": AS_OF.isoformat(), "declared": declared,
            "quiz_answers": spec["quiz"], "situations_answers": spec["situations"], "transactions": txs}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for key, spec in PROFILES.items():
        data = build_one(key, spec)
        (OUT / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"{key}: {len(data['transactions'])} transactions")


if __name__ == "__main__":
    main()
