"""Étape 3 : comparaison profil / action et contraintes."""

import copy
import dataclasses
import unittest
from datetime import date

from agent_risque import asset_score, combine, comparison, config, constraints, data_access
from agent_risque.fixtures import personas


def setUpModule():
    config.SCORE_MODEL_VERSION = "v1"     # ces tests décrivent la mécanique du modèle v1 (quiz) ; v2 : test_model_v2.py


def tearDownModule():
    config.SCORE_MODEL_VERSION = "v2"


AS_OF = date(2026, 11, 12)
RANK = {"vert": 0, "jaune": 1, "rouge": 2}

_PROFILES = {n: combine.compute_user_profile(**a, model_version="v1") for n, a in personas.all_personas().items()}
_ASSETS = {t: asset_score.score_asset(t, AS_OF) for t in data_access.load_universe()}


def _profile_with(score: float, confidence: float = 1.0) -> dict:
    """Profil synthétique (copie d'un profil réel) avec un score et une confiance imposés."""
    p = copy.deepcopy(_PROFILES["mateo"])
    p["final_score"] = score
    p["confidence"]["value"] = confidence
    p["history"]["score"] = score
    p["quiz"]["score"] = score
    return p


def _asset_with(score: float, ticker: str = "SPY"):
    return dataclasses.replace(_ASSETS[ticker], score=score)


class ConfigTests(unittest.TestCase):
    def test_thresholds_are_ordered(self):
        self.assertLess(0, config.VERDICT_GREEN_MAX_GAP)
        self.assertLess(config.VERDICT_GREEN_MAX_GAP, config.VERDICT_YELLOW_MAX_GAP)
        self.assertLess(config.VERDICT_TOO_SAFE_GAP, 0)
        self.assertLess(config.CONFIDENCE_LABEL_LOW_MAX, config.CONFIDENCE_LABEL_MEDIUM_MAX)
        self.assertLess(config.CONSTRAINT_SINGLE_NAME_ATTENTION, config.SINGLE_NAME_MAX_WEIGHT)
        self.assertEqual(set(config.VERDICT_HEADLINES), set(comparison.COLORS))


class VerdictTests(unittest.TestCase):
    def test_repeatable(self):
        for name, p in _PROFILES.items():
            for t in ("ZST.TO", "SPY", "TSLA"):
                with self.subTest(persona=name, ticker=t):
                    self.assertEqual(comparison.compare(p, _ASSETS[t]), comparison.compare(p, _ASSETS[t]))

    def test_exact_thresholds(self):
        p = _profile_with(40.0)
        cases = [(50.0, "vert"), (50.01, "jaune"), (65.0, "jaune"), (65.01, "rouge"), (0.0, "vert")]
        for asset_value, expected in cases:
            with self.subTest(asset=asset_value):
                self.assertEqual(comparison.compare(p, _asset_with(asset_value))["risk_color"], expected)

    def test_too_safe_flag_keeps_color_green(self):
        p = _profile_with(60.0)
        r = comparison.compare(p, _asset_with(30.0))        # écart = -30
        self.assertTrue(r["too_safe"])
        self.assertEqual(r["risk_color"], "vert")
        self.assertIn(config.VERDICT_TOO_SAFE_MESSAGE, r["summary_fr"])
        self.assertFalse(comparison.compare(p, _asset_with(30.01))["too_safe"])

    def test_riskier_asset_never_gets_a_better_color(self):
        for name, p in _PROFILES.items():
            ranked = sorted(_ASSETS.values(), key=lambda a: a.score)
            colors = [RANK[comparison.compare(p, a)["risk_color"]] for a in ranked]
            with self.subTest(persona=name):
                self.assertEqual(colors, sorted(colors))

    def test_more_tolerant_profile_never_gets_a_worse_color(self):
        order = ["robert", "mateo", "amira"]
        for t, a in _ASSETS.items():
            colors = [RANK[comparison.compare(_PROFILES[n], a)["risk_color"]] for n in order]
            with self.subTest(ticker=t):
                self.assertEqual(colors, sorted(colors, reverse=True))

    def test_low_confidence_never_makes_the_verdict_greener(self):
        for asset_value in (20.0, 45.0, 60.0, 80.0):
            colors = [RANK[comparison.compare(_profile_with(50.0, c), _asset_with(asset_value))["risk_color"]]
                      for c in (1.0, 0.8, 0.5, 0.2, 0.0)]
            with self.subTest(asset=asset_value):
                self.assertEqual(colors, sorted(colors))

    def test_uncertainty_margin_values(self):
        r = comparison.compare(_profile_with(50.0, 0.5), _asset_with(60.0))
        self.assertAlmostEqual(r["user"]["effective_tolerance"], 50.0 - 7.5)
        self.assertAlmostEqual(r["gap"], 60.0 - 42.5)

    def test_robustness_flags_profile_depending_on_source(self):
        robert = _PROFILES["robert"]
        sensitive = comparison.compare(robert, _ASSETS["XIU.TO"])
        self.assertFalse(sensitive["robustness"]["robust"])
        self.assertTrue(sensitive["robustness"]["sensitive_to"])
        robust = comparison.compare(robert, _ASSETS["ZST.TO"])
        self.assertTrue(robust["robustness"]["robust"])

    def test_drivers_sorted_and_shares_sum_to_one(self):
        r = comparison.compare(_PROFILES["robert"], _ASSETS["TSLA"])
        weighted = [d["weighted_excess"] for d in r["drivers"]]
        self.assertEqual(weighted, sorted(weighted, reverse=True))
        self.assertAlmostEqual(sum(d["share_of_excess"] for d in r["drivers"]), 1.0, places=3)
        self.assertEqual(len(r["drivers"]), 4)          # actualité indisponible : exclue

    def test_profile_evidence_is_reported(self):
        r = comparison.compare(_PROFILES["amira"], _ASSETS["NVDA"])
        self.assertIsNotNone(r["profile_evidence"]["volatility"])
        self.assertIsNotNone(r["profile_evidence"]["drop_reaction"])

    def test_confidence_is_the_lowest_and_capped_without_news(self):
        for p in _PROFILES.values():
            r = comparison.compare(p, _ASSETS["SPY"])
            self.assertAlmostEqual(r["confidence"]["value"],
                                   min(p["confidence"]["value"], _ASSETS["SPY"].confidence["value"]), places=3)
            self.assertNotEqual(r["confidence"]["label"], "élevée")      # actualité absente
        self.assertEqual(_ASSETS["SPY"].confidence["label"], "moyenne")
        self.assertEqual(_PROFILES["mateo"]["confidence"]["label"], "élevée")

    def test_dates_must_match(self):
        other = asset_score.score_asset("SPY", date(2026, 11, 9))
        with self.assertRaises(ValueError):
            comparison.compare(_PROFILES["robert"], other)

    def test_language_describes_fit_and_never_pushes_a_trade(self):
        forbidden = ("achetez", "vendez", "nous recommandons", "vous devriez")
        for p in _PROFILES.values():
            for t in ("ZST.TO", "SPY", "BTC-USD"):
                text = " ".join(comparison.compare(p, _ASSETS[t])["summary_fr"]).lower()
                for w in forbidden:
                    self.assertNotIn(w, text)

    def test_disclaimers_present(self):
        r = comparison.compare(_PROFILES["robert"], _ASSETS["SPY"])
        self.assertEqual(len(r["disclaimers"]), len(config.ASSET_DISCLAIMERS))


class ConstraintTests(unittest.TestCase):
    def _status(self, result, key):
        return next(c["status"] for c in result["constraints"] if c["key"] == key)

    def test_mateo_is_challenged_on_an_energy_stock_he_excluded(self):
        r = comparison.compare(_PROFILES["mateo"], _ASSETS["XOM"])
        self.assertEqual(self._status(r, "exclusions"), constraints.STATUS_VIOLATION)
        self.assertEqual(r["final_color"], "rouge")

    def test_robert_is_challenged_on_a_crypto_by_his_horizon(self):
        r = comparison.compare(_PROFILES["robert"], _ASSETS["BTC-USD"])
        self.assertEqual(self._status(r, "horizon"), constraints.STATUS_ATTENTION)
        self.assertEqual(r["final_color"], "rouge")

    def test_prudent_profile_on_safe_asset_has_no_constraint_issue(self):
        r = comparison.compare(_PROFILES["robert"], _ASSETS["ZST.TO"])
        self.assertEqual(self._status(r, "exclusions"), constraints.STATUS_OK)
        self.assertEqual(self._status(r, "horizon"), constraints.STATUS_OK)
        self.assertEqual(r["final_color"], "vert")

    def test_short_horizon_with_high_risk_asset_raises_attention(self):
        r = comparison.compare(_PROFILES["robert"], _ASSETS["AMZN"])
        self.assertEqual(self._status(r, "horizon"), constraints.STATUS_ATTENTION)
        self.assertEqual(comparison.compare(_PROFILES["robert"], _ASSETS["AAPL"])["constraints"][1]["status"],
                         constraints.STATUS_OK)

    def test_esg_preference_is_reported_as_not_verifiable(self):
        r = comparison.compare(_PROFILES["mateo"], _ASSETS["SPY"])
        esg = next(c for c in r["constraints"] if c["key"] == "preference:ESG")
        self.assertEqual(esg["status"], constraints.STATUS_NOT_VERIFIABLE)
        self.assertIn("aucune note ESG", esg["message"])

    def test_amira_gets_the_too_safe_message_on_a_very_safe_asset(self):
        r = comparison.compare(_PROFILES["amira"], _ASSETS["ZST.TO"])
        self.assertEqual(r["risk_color"], "vert")
        self.assertTrue(r["too_safe"])

    def test_concentration_needs_an_amount(self):
        r = comparison.compare(_PROFILES["amira"], _ASSETS["NVDA"])
        self.assertEqual(self._status(r, "concentration"), constraints.STATUS_NOT_EVALUATED)

    def test_concentration_after_a_very_large_purchase_is_a_violation(self):
        r = comparison.compare(_PROFILES["amira"], _ASSETS["NVDA"], planned_amount_cad=10_000_000)
        self.assertEqual(self._status(r, "concentration"), constraints.STATUS_VIOLATION)
        self.assertEqual(r["risk_color"], "vert")           # le risque seul serait vert
        self.assertEqual(r["final_color"], "rouge")         # la contrainte relève la couleur

    def test_small_purchase_keeps_a_diversified_portfolio_ok(self):
        r = comparison.compare(_PROFILES["mateo"], _ASSETS["SPY"], planned_amount_cad=500)
        self.assertEqual(self._status(r, "concentration"), constraints.STATUS_OK)

    def test_final_color_is_the_worst_of_risk_and_constraints(self):
        for name, p in _PROFILES.items():
            for t, a in _ASSETS.items():
                r = comparison.compare(p, a, planned_amount_cad=1000)
                worst = max([RANK[r["risk_color"]]] + [constraints.STATUS_COLOR_RANK.get(c["status"], 0)
                                                       for c in r["constraints"]])
                with self.subTest(persona=name, ticker=t):
                    self.assertEqual(RANK[r["final_color"]], worst)

    def test_empty_portfolio_does_not_flag_concentration(self):
        p = combine.compute_user_profile("vide", AS_OF, [], personas.all_personas()["mateo"]["quiz_answers"])
        r = comparison.compare(p, _ASSETS["NVDA"], planned_amount_cad=1000)
        self.assertEqual(self._status(r, "concentration"), constraints.STATUS_NOT_EVALUATED)

    def test_invalid_amount_rejected(self):
        with self.assertRaises(ValueError):
            comparison.compare(_PROFILES["robert"], _ASSETS["SPY"], planned_amount_cad=0)

    def test_legacy_declared_format_is_ignored_with_a_warning(self):
        args = dict(personas.all_personas()["robert"],
                    declared={"horizon_years": "3-5", "exclusions": ["crypto"]})
        p = combine.compute_user_profile(**args)
        r = comparison.compare(p, _ASSETS["BTC-USD"])
        self.assertEqual(self._status(r, "horizon"), constraints.STATUS_NOT_EVALUATED)
        self.assertEqual(self._status(r, "exclusions"), constraints.STATUS_OK)
        self.assertEqual(sum("ignoré" in w for w in r["warnings"]), 2)

    def test_exclusion_by_sector_and_ticker(self):
        base = personas.all_personas()["mateo"]
        sector = data_access.get_asset("ENB.TO").sector
        for excl, ticker in ((({"sectors": [sector]}), "ENB.TO"), ({"tickers": ["jnj"]}, "JNJ")):
            p = combine.compute_user_profile(**dict(base, declared={"exclusions": excl}))
            r = comparison.compare(p, _ASSETS[ticker])
            with self.subTest(exclusion=excl):
                self.assertEqual(self._status(r, "exclusions"), constraints.STATUS_VIOLATION)


class ConfidenceLabelTests(unittest.TestCase):
    def test_asset_label_is_capped_while_news_is_missing(self):
        for a in _ASSETS.values():
            self.assertNotEqual(a.confidence["label"], "élevée")
            self.assertTrue(a.confidence["label_capped_for_missing_news"])

    def test_labels_follow_thresholds(self):
        self.assertEqual(combine.confidence_label(0.59), "faible")
        self.assertEqual(combine.confidence_label(0.6), "moyenne")
        self.assertEqual(combine.confidence_label(0.9), "élevée")
        self.assertEqual(combine.lowest_label("élevée", "moyenne", "élevée"), "moyenne")


if __name__ == "__main__":
    unittest.main()
