"""Intégrité : configuration valide, aucune anticipation, aucune donnée inventée."""

import unittest
from datetime import date

from agent_risque import config, history_score, metrics
from agent_risque.transactions import Transaction, validate_and_sort

AS_OF = date(2026, 11, 12)


class ConfigTests(unittest.TestCase):
    def test_indicator_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(config.INDICATOR_WEIGHTS.values()), 1.0)
        self.assertEqual(set(config.INDICATOR_WEIGHTS), set(history_score.LABELS))

    def test_confidence_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(config.CONFIDENCE_WEIGHTS.values()), 1.0)

    def test_vol_anchors_strictly_increasing(self):
        xs = [x for x, _ in config.VOL_ANCHORS]
        ys = [y for _, y in config.VOL_ANCHORS]
        self.assertEqual(xs, sorted(set(xs)))
        self.assertEqual(ys, sorted(ys))
        self.assertEqual((ys[0], ys[-1]), (0.0, 100.0))

    def test_quiz_is_well_formed(self):
        self.assertEqual(len(config.QUIZ_QUESTIONS), 5)
        ids = [q["id"] for q in config.QUIZ_QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for q in config.QUIZ_QUESTIONS:
            points = [p for _, p in q["answers"]]
            self.assertEqual(len(points), 4)
            self.assertEqual(points, sorted(points))
            self.assertTrue(all(0 <= p <= 100 for p in points))

    def test_thresholds_are_consistent(self):
        self.assertLess(config.RISK_BUCKET_LOW_MAX, config.RISK_BUCKET_HIGH_MIN)
        self.assertGreater(config.N_EFF_TARGET, 1)
        self.assertGreaterEqual(config.HISTORY_WEIGHT_BASE, 0.0)
        self.assertLessEqual(config.HISTORY_WEIGHT_BASE, 1.0)

    def test_fingerprint_is_stable(self):
        self.assertEqual(config.fingerprint(), config.fingerprint())


class DataIntegrityTests(unittest.TestCase):
    def test_future_transaction_rejected(self):
        trades, warnings = validate_and_sort([Transaction(date(2026, 12, 1), "SPY", "buy", 1)], AS_OF)
        self.assertEqual(trades, [])
        self.assertTrue(any("postérieure" in w for w in warnings))

    def test_unknown_ticker_rejected(self):
        trades, warnings = validate_and_sort([Transaction(date(2025, 6, 2), "ZZZZ", "buy", 1)], AS_OF)
        self.assertEqual(trades, [])
        self.assertTrue(any("absent des données" in w for w in warnings))

    def test_no_price_that_day_rejected(self):
        # Le 2025-06-01 est un dimanche : AAPL ne cote pas, aucun prix n'est inventé.
        trades, warnings = validate_and_sort([Transaction(date(2025, 6, 1), "AAPL", "buy", 1)], AS_OF)
        self.assertEqual(trades, [])
        self.assertTrue(any("aucun prix" in w for w in warnings))

    def test_oversell_rejected(self):
        txs = [Transaction(date(2025, 6, 2), "SPY", "buy", 1), Transaction(date(2025, 6, 3), "SPY", "sell", 2)]
        trades, warnings = validate_and_sort(txs, AS_OF)
        self.assertEqual(len(trades), 1)
        self.assertTrue(any("supérieure à la position" in w for w in warnings))

    def test_bad_quantity_and_side_rejected(self):
        txs = [Transaction(date(2025, 6, 2), "SPY", "buy", 0), Transaction(date(2025, 6, 2), "SPY", "hold", 1)]
        trades, warnings = validate_and_sort(txs, AS_OF)
        self.assertEqual(trades, [])
        self.assertEqual(len(warnings), 2)

    def test_insufficient_price_history_is_reported_not_assumed(self):
        # Début des données : 2021-11-12. Un achat en janvier 2022 n'a pas 120 rendements avant lui.
        trades, _ = validate_and_sort([Transaction(date(2022, 1, 4), "SPY", "buy", 1)], AS_OF)
        warnings: list[str] = []
        ind = history_score._volatility_indicator(trades, warnings)
        self.assertFalse(ind.available)
        self.assertTrue(any("insuffisant" in w for w in warnings))

    def test_volatility_uses_only_information_before_the_trade(self):
        txs = [Transaction(date(2025, 6, 2), "NVDA", "buy", 10)]
        trades_early, _ = validate_and_sort(txs, date(2025, 7, 1))
        early = history_score._volatility_indicator(trades_early, [])
        # Même achat, mais on regarde 16 mois plus tard : l'indicateur ne doit pas bouger.
        trades_later, _ = validate_and_sort(txs, AS_OF)
        later = history_score._volatility_indicator(trades_later, [])
        self.assertEqual(early.raw_value, later.raw_value)
        # Et la fenêtre exclut le jour de la transaction lui-même.
        with_end = metrics.trailing_vol_pct("NVDA", date(2025, 6, 2), include_end=True)
        without_end = metrics.trailing_vol_pct("NVDA", date(2025, 6, 2), include_end=False)
        self.assertNotEqual(with_end, without_end)
        self.assertEqual(early.raw_value, without_end)

    def test_drop_events_ignore_windows_not_finished_before_as_of(self):
        txs = [Transaction(date(2026, 1, 5), "TSLA", "buy", 10)]
        trades, _ = validate_and_sort(txs, date(2026, 1, 20))
        events = history_score._drop_events("TSLA", trades, date(2026, 1, 20))
        for e in events:
            self.assertLess(e["drop_date"], "2026-01-20")


if __name__ == "__main__":
    unittest.main()
