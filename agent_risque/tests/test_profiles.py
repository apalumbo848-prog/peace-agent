"""Les 4 profils fictifs (Amira, Mateo, Robert, Léa) : historiques fixes, scores et verdicts attendus.

Limite assumée : le jeu de données ne contient aucune note ESG. Le test de Mateo vérifie donc son EXCLUSION déclarée du
secteur Énergie (vérifiable avec les données), pas une note ESG ; sa préférence « ESG » reste « non vérifiable ».
"""

import json
import unittest
from datetime import timedelta

from agent_risque import asset_score, combine, comparison, constraints, data_access, history_score
from agent_risque.fixtures import build_profiles, personas
from agent_risque.transactions import Transaction, validate_and_sort

AS_OF = personas.AS_OF
MIN_GAP = 10.0                                        # « nettement différents » : au moins 10 points d'écart
ARGS = personas.all_personas()
PROFILES = {k: combine.compute_user_profile(**a) for k, a in ARGS.items()}
ASSETS: dict = {}


def asset(ticker):
    if ticker not in ASSETS:
        ASSETS[ticker] = asset_score.score_asset(ticker, AS_OF)
    return ASSETS[ticker]


def verdict(persona, ticker, amount=2000.0):
    return comparison.compare(PROFILES[persona], asset(ticker), amount)


def status(v, key):
    return next(c["status"] for c in v["constraints"] if c["key"] == key)


class HistoryFilesTests(unittest.TestCase):
    def test_counts_and_periods(self):
        n = {k: len(a["transactions"]) for k, a in ARGS.items()}
        self.assertGreaterEqual(n["amira"], 38)
        self.assertLessEqual(n["amira"], 42)
        self.assertEqual((n["mateo"], n["robert"], n["lea"]), (20, 10, 0))
        years = lambda k: (ARGS[k]["transactions"][-1].date - ARGS[k]["transactions"][0].date).days / 365.25
        self.assertGreater(years("amira"), 2.9)
        self.assertGreater(years("mateo"), 4.9)

    def test_every_transaction_uses_real_prices_on_covered_dates(self):
        for key in ("amira", "mateo", "robert"):
            data = json.loads((personas.PROFILES_DIR / f"{key}.json").read_text(encoding="utf-8"))
            for t in data["transactions"]:
                self.assertEqual(set(t), {"date", "ticker", "side", "quantity", "price", "currency"})
                d = personas.date.fromisoformat(t["date"])
                bars = data_access.get_prices(t["ticker"], d, d)
                self.assertEqual(len(bars), 1, f"{key} {t['ticker']} {t['date']} : pas de cotation ce jour-là")
                self.assertAlmostEqual(bars[0].close, t["price"], places=3)
                self.assertGreater(t["quantity"], 0)

    def test_files_are_reproducible_without_randomness(self):
        for key, spec in build_profiles.PROFILES.items():
            on_disk = json.loads((personas.PROFILES_DIR / f"{key}.json").read_text(encoding="utf-8"))
            self.assertEqual(build_profiles.build_one(key, spec), on_disk, key)

    def test_declared_fields(self):
        d = {k: a["declared"] for k, a in ARGS.items()}
        self.assertEqual([d[k]["age"] for k in personas.ORDER], [26, 41, 59, 18])
        self.assertEqual(d["amira"]["horizon_years"], [15, None])
        self.assertEqual(d["mateo"]["horizon_years"], [8, 12])
        self.assertEqual(d["robert"]["horizon_years"], [3, 5])
        self.assertIn("ESG", d["mateo"]["preferences"])
        self.assertEqual(d["mateo"]["exclusions"]["sectors"], ["Energy"])
        for k in personas.ORDER:
            self.assertIn("objective", d[k])
            self.assertEqual(len(ARGS[k]["quiz_answers"]), 5)

    def _values(self, key):
        txs, _ = validate_and_sort(list(ARGS[key]["transactions"]), AS_OF)
        values, _ = history_score.current_portfolio_values(txs, AS_OF)
        return values

    def test_amira_is_concentrated_in_three_tech_stocks(self):
        values = self._values("amira")
        total = sum(values.values())
        tech = sorted((v for t, v in values.items() if data_access.get_asset(t).sector == "Information Technology"), reverse=True)
        self.assertGreater(sum(tech[:3]) / total, 0.5)
        self.assertGreater(sum(v for t, v in values.items() if data_access.get_asset(t).asset_class == "crypto") / total, 0.1)

    def test_amira_buys_during_drops(self):
        dip_buys = 0
        for t in ARGS["amira"]["transactions"]:
            if t.side != "buy":
                continue
            window = data_access.get_prices(t.ticker, t.date - timedelta(days=90), t.date)
            high = max(b.close for b in window)
            if window[-1].close <= 0.90 * high:
                dip_buys += 1
        self.assertGreaterEqual(dip_buys, 12)

    def test_mateo_sold_oil_and_never_bought_it_back(self):
        oil = {"XOM", "CNQ.TO"}
        for tk in oil:
            sides = [t.side for t in ARGS["mateo"]["transactions"] if t.ticker == tk]
            self.assertEqual(sides[-1], "sell", tk)
        self.assertNotIn("sell", {t.side for t in ARGS["mateo"]["transactions"] if t.ticker not in oil})   # ne vend jamais ailleurs
        self.assertTrue(all(v == 0 for tk, v in self._values("mateo").items() if tk in oil))

    def test_robert_sold_in_a_big_drop_and_made_an_impulsive_trade_at_a_loss(self):
        txs = ARGS["robert"]["transactions"]
        enb_sell = next(t for t in txs if t.ticker == "ENB.TO" and t.side == "sell")
        window = data_access.get_prices("ENB.TO", enb_sell.date - timedelta(days=500), enb_sell.date)
        self.assertLessEqual(window[-1].close, 0.75 * max(b.close for b in window))              # forte baisse
        buy = next(t for t in txs if t.ticker == "TSLA" and t.side == "buy")
        sell = next(t for t in txs if t.ticker == "TSLA" and t.side == "sell")
        self.assertLess((sell.date - buy.date).days, 90)                                         # quelques semaines
        self.assertLess(data_access.get_prices("TSLA", sell.date, sell.date)[0].close,
                        data_access.get_prices("TSLA", buy.date, buy.date)[0].close)             # revendu à perte


class ScoreTests(unittest.TestCase):
    def test_scores_are_clearly_different_and_ordered(self):
        s = {k: PROFILES[k]["final_score"] for k in ("amira", "mateo", "robert")}
        self.assertGreater(s["amira"] - s["mateo"], MIN_GAP)
        self.assertGreater(s["mateo"] - s["robert"], MIN_GAP)

    def test_lea_depends_on_her_answers(self):
        bold = dict(ARGS["lea"], situations_answers=[personas._resp(t, 5, 3, 3) for t in ("SPY", "QQQ", "XIU.TO")])
        cautious = dict(ARGS["lea"], situations_answers=[personas._resp(t, 0, 0, 0) for t in ("SPY", "QQQ", "XIU.TO")])
        hi, lo = combine.compute_user_profile(**bold), combine.compute_user_profile(**cautious)
        self.assertGreater(hi["final_score"] - lo["final_score"], 40)
        self.assertGreater(hi["final_score"], PROFILES["lea"]["final_score"])
        self.assertGreater(PROFILES["lea"]["final_score"], lo["final_score"])

    def test_lea_works_without_any_transaction(self):
        p = PROFILES["lea"]
        self.assertEqual(ARGS["lea"]["transactions"], [])
        self.assertIsNone(p["history"]["score"])
        self.assertEqual(p["components"]["history"]["effective_weight"], 0.0)
        self.assertEqual(p["final_score"], p["situations"]["score"])                 # 100 % sur ses réponses
        self.assertEqual(p["confidence"]["label"], "faible")
        self.assertLess(p["confidence"]["value"], 0.3)
        for t in ("SPY", "NVDA", "ZST.TO", "BTC-USD"):                               # le verdict se calcule aussi
            self.assertIn(verdict("lea", t)["final_color"], ("vert", "jaune", "rouge"))
        self.assertEqual(status(verdict("lea", "SPY"), "concentration"), constraints.STATUS_NOT_EVALUATED)


class VerdictTests(unittest.TestCase):
    def test_amira_very_risky_stock_in_her_concentrated_sector_is_not_green(self):
        for ticker in ("NVDA", "SHOP.TO"):
            self.assertGreaterEqual(asset(ticker).score, 80, ticker)                 # très risquée
            self.assertEqual(data_access.get_asset(ticker).sector, "Information Technology")
            v = verdict("amira", ticker)
            self.assertNotEqual(v["final_color"], "vert", ticker)
            self.assertIn(status(v, "concentration"), (constraints.STATUS_ATTENTION, constraints.STATUS_VIOLATION), ticker)

    def test_amira_even_a_moderate_tech_stock_is_raised_by_concentration(self):
        v = verdict("amira", "MSFT")
        self.assertEqual(v["risk_color"], "vert")                                    # le risque seul lui convient
        self.assertNotEqual(v["final_color"], "vert")                                # la concentration relève le verdict

    def test_mateo_energy_stock_is_flagged_even_when_its_risk_suits(self):
        suits = [t for t in ("ENB.TO", "XOM", "CNQ.TO") if verdict("mateo", t)["risk_color"] != "rouge"]
        self.assertTrue(suits)                                                       # au moins un titre dont le risque lui convient
        for t in ("ENB.TO", "XOM", "CNQ.TO"):
            v = verdict("mateo", t)
            self.assertEqual(status(v, "exclusions"), constraints.STATUS_VIOLATION, t)
            self.assertEqual(v["final_color"], "rouge", t)
        v = verdict("mateo", suits[0])
        self.assertIn(v["risk_color"], ("vert", "jaune"))
        self.assertEqual(status(verdict("mateo", "SPY"), "exclusions"), constraints.STATUS_OK)

    def test_mateo_esg_preference_is_honestly_not_verifiable(self):
        self.assertEqual(status(verdict("mateo", "SPY"), "preference:ESG"), constraints.STATUS_NOT_VERIFIABLE)
        self.assertEqual(status(verdict("mateo", "ESGV"), "preference:ESG"), constraints.STATUS_OK)      # fonds filtré ESG : reconnu

    def test_amira_tech_and_crypto_preferences_are_checked_against_the_data(self):
        nvda, btc = verdict("amira", "NVDA"), verdict("amira", "BTC-USD")
        self.assertEqual(next(c for c in nvda["constraints"] if c["key"] == "preference:technologie")["details"]["matches"], True)
        self.assertEqual(next(c for c in nvda["constraints"] if c["key"] == "preference:crypto")["details"]["matches"], False)
        self.assertEqual(next(c for c in btc["constraints"] if c["key"] == "preference:crypto")["details"]["matches"], True)

    def test_robert_volatile_stock_is_flagged_against_profile_and_horizon(self):
        for ticker in ("TSLA", "NVDA", "BTC-USD"):
            v = verdict("robert", ticker)
            self.assertEqual(v["final_color"], "rouge", ticker)
            self.assertEqual(status(v, "horizon"), constraints.STATUS_ATTENTION, ticker)
            self.assertTrue(any("horizon" in line for line in v["summary_fr"]), ticker)
        self.assertEqual(verdict("robert", "ZST.TO")["final_color"], "vert")


if __name__ == "__main__":
    unittest.main()
