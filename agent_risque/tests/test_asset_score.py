"""Étape 2 : score de risque d'une action."""

import unittest
from datetime import date
from unittest import mock

from agent_risque import asset_score, config, data_access, metrics
from agent_risque.asset_score import AssetScoreError, score_asset

AS_OF = date(2026, 11, 12)


class AssetConfigTests(unittest.TestCase):
    def test_weights_and_anchors(self):
        self.assertAlmostEqual(sum(config.ASSET_COMPONENT_WEIGHTS.values()), 1.0)
        self.assertAlmostEqual(sum(config.ASSET_CONFIDENCE_WEIGHTS.values()), 1.0)
        self.assertEqual(set(config.ASSET_COMPONENT_WEIGHTS), set(asset_score.LABELS))
        for name in ("ASSET_DRAWDOWN_ANCHORS", "ASSET_TAIL_ANCHORS", "ASSET_STRESS_ANCHORS"):
            anchors = getattr(config, name)
            xs = [x for x, _ in anchors]
            ys = [y for _, y in anchors]
            with self.subTest(anchors=name):
                self.assertEqual(xs, sorted(set(xs)))
                self.assertEqual(ys, sorted(ys))
                self.assertEqual((ys[0], ys[-1]), (0.0, 100.0))


class AssetScoreTests(unittest.TestCase):
    def test_repeatable(self):
        for t in ("SPY", "NVDA", "BTC-USD", "ZST.TO"):
            with self.subTest(ticker=t):
                self.assertEqual(score_asset(t, AS_OF).to_dict(), score_asset(t, AS_OF).to_dict())

    def test_ordering_from_stable_to_risky(self):
        order = ["ZST.TO", "XBB.TO", "SPY", "AAPL", "NVDA", "ETH-USD"]
        scores = [score_asset(t, AS_OF).score for t in order]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(len(set(scores)), len(scores))

    def test_common_scale_anchors(self):
        self.assertLess(score_asset("ZST.TO", AS_OF).score, 5.0)
        self.assertGreater(score_asset("ETH-USD", AS_OF).score, 90.0)

    def test_every_asset_in_universe_gets_a_score_in_range(self):
        for t in data_access.load_universe():
            with self.subTest(ticker=t):
                r = score_asset(t, AS_OF)
                self.assertGreaterEqual(r.score, 0.0)
                self.assertLessEqual(r.score, 100.0)

    def test_decomposition_adds_up(self):
        for t in ("SPY", "TSLA", "GLD"):
            r = score_asset(t, AS_OF)
            with self.subTest(ticker=t):
                self.assertAlmostEqual(sum(c.contribution for c in r.components), r.score, places=9)
                self.assertAlmostEqual(sum(c.effective_weight for c in r.components if c.available), 1.0)
                for c in r.components:
                    if c.available:
                        self.assertAlmostEqual(c.contribution, c.effective_weight * c.points, places=9)

    def test_news_component_is_reserved_and_unavailable(self):
        r = score_asset("SPY", AS_OF)
        news = next(c for c in r.components if c.key == "news")
        self.assertFalse(news.available)
        self.assertEqual(news.effective_weight, 0.0)
        self.assertTrue(news.note)
        self.assertAlmostEqual(r.confidence["parts"]["coverage"], 0.8)
        self.assertTrue(any("Actualité" in w for w in r.warnings))

    def test_volatility_uses_the_same_scale_as_the_user_score(self):
        r = score_asset("AAPL", AS_OF)
        vol = next(c for c in r.components if c.key == "volatility")
        self.assertAlmostEqual(vol.points, metrics.vol_to_points(vol.raw_value))

    def test_no_look_ahead(self):
        """Avec les données tronquées à as_of, le score est strictement identique."""
        as_of = date(2024, 6, 3)
        full = {t: score_asset(t, as_of).to_dict() for t in ("SPY", "NVDA", "BTC-USD")}
        original = data_access._load_prices()
        truncated = {}
        for ticker, (dates, bars) in original.items():
            kept = [b for b in bars if b.date <= as_of]
            truncated[ticker] = (tuple(b.date for b in kept), tuple(kept))
        with mock.patch.object(data_access, "_load_prices", return_value=truncated):
            for t, expected in full.items():
                with self.subTest(ticker=t):
                    self.assertEqual(score_asset(t, as_of).to_dict(), expected)
        r = score_asset("SPY", as_of)
        self.assertLessEqual(r.window_end, as_of.isoformat())

    def test_unknown_ticker_and_short_history_raise_clear_errors(self):
        with self.assertRaises(AssetScoreError) as ctx:
            score_asset("ZZZZ", AS_OF)
        self.assertIn("inconnu", str(ctx.exception))
        with self.assertRaises(AssetScoreError) as ctx:
            score_asset("SPY", date(2022, 6, 1))     # ~135 rendements seulement
        self.assertIn("insuffisant", str(ctx.exception))

    def test_regime_shift_lowers_confidence_and_warns(self):
        stable = score_asset("SPY", AS_OF)
        shifted = score_asset("GLD", AS_OF)       # 19,3 % sur 5 ans contre 29,2 % sur 1 an
        self.assertLess(shifted.confidence["parts"]["stability"], stable.confidence["parts"]["stability"])
        self.assertLess(shifted.confidence["value"], stable.confidence["value"])
        self.assertTrue(any("Changement de régime" in w for w in shifted.warnings))
        self.assertFalse(any("Changement de régime" in w for w in stable.warnings))

    def test_known_issue_and_currency_warnings(self):
        cnq = score_asset("CNQ.TO", AS_OF)
        self.assertTrue(any("1,021" in w for w in cnq.warnings))
        self.assertFalse(any("taux de change" in w for w in cnq.warnings))
        self.assertTrue(any("taux de change" in w for w in score_asset("AAPL", AS_OF).warnings))

    def test_sources_and_disclaimers_are_reported(self):
        r = score_asset("SPY", AS_OF)
        self.assertTrue(any("Yahoo" in s["source"] for s in r.data_sources))
        self.assertEqual(len(r.disclaimers), len(config.ASSET_DISCLAIMERS))

    def test_crypto_has_longer_history_but_scores_on_its_own_calendar(self):
        btc = score_asset("BTC-USD", AS_OF)
        spy = score_asset("SPY", AS_OF)
        self.assertGreater(btc.n_returns, spy.n_returns)
        self.assertGreater(btc.score, spy.score)

    def test_metrics_helpers(self):
        self.assertAlmostEqual(metrics.max_drawdown_pct([100, 120, 60, 90]), 50.0)
        self.assertEqual(metrics.max_drawdown_pct([1, 2, 3]), 0.0)
        self.assertAlmostEqual(metrics.current_drawdown_pct([100, 120, 90], 252), 25.0)
        self.assertGreater(metrics.cvar_pct([100, 90, 100, 99, 100, 98, 100, 100, 101, 102], 0.2), 0.0)


if __name__ == "__main__":
    unittest.main()
