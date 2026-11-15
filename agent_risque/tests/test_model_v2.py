"""Tests du modèle de tolérance v2 : mises en situation, historique à 6 indicateurs, combinaison, parcours web."""

from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from agent_risque import combine, config, history_v2, metrics, situations
from agent_risque.app import server, service, situation_ledger
from agent_risque.fixtures import personas
from agent_risque.history_score import HistoryResult
from agent_risque.transactions import Trade

AS_OF = personas.AS_OF


def resp(ticker="SPY", ladder=3, reaction=1, tradeoff=1):
    return personas._resp(ticker, ladder, reaction, tradeoff)


class SituationScoringTests(unittest.TestCase):
    def test_known_points(self):
        s = situations.score_response(situations.validate_response(resp(ladder=5, reaction=3, tradeoff=3)))
        self.assertAlmostEqual(s["ladder_points"], metrics.interpolate(50.0, config.SITUATION_LADDER_ANCHORS))
        self.assertAlmostEqual(s["score"], 0.5 * s["ladder_points"] + 30 + 20)
        zero = situations.score_response(situations.validate_response(resp(ladder=0, reaction=0, tradeoff=0)))
        self.assertEqual(zero["score"], 0.0)

    def test_ladder_uses_same_scale_as_asset_drawdown(self):
        s = situations.score_response(situations.validate_response(resp(ladder=3)))     # 30 % acceptés
        self.assertEqual(s["max_accepted_loss_pct"], 30)
        self.assertAlmostEqual(s["ladder_points"], metrics.interpolate(30.0, config.ASSET_DRAWDOWN_ANCHORS))

    def test_monotonic_more_risk_accepted_never_lowers_score(self):
        for field in ("ladder", "reaction", "tradeoff"):
            top = {"ladder": 5, "reaction": 3, "tradeoff": 3}[field]
            scores = [situations.score_response(situations.validate_response(resp(**{field: k})))["score"]
                      for k in range(top + 1)]
            self.assertEqual(scores, sorted(scores), field)

    def test_inconsistent_answers_are_flagged_and_lower_reliability(self):
        bad = {"ticker": "SPY", "ladder": [True, False, True], "reaction": 1, "tradeoff": [False, True, False]}
        good = resp()
        r_good = situations.score_situations([good] * 6)
        r_bad = situations.score_situations([bad] * 6)
        self.assertFalse(situations.score_response(situations.validate_response(bad))["consistent"])
        self.assertLess(r_bad.reliability, r_good.reliability)
        self.assertTrue(any("contradictoire" in w for w in r_bad.warnings))

    def test_skipped_and_invalid_are_ignored(self):
        r = situations.score_situations([{"ticker": "SPY", "skipped": True}, {"ticker": "QQQ", "ladder": "x"}, resp()])
        self.assertEqual(r.n_answered, 1)
        self.assertEqual(situations.score_situations([{"ticker": "SPY", "skipped": True}]).score, None)
        self.assertEqual(situations.score_situations(None).score, None)

    def test_reliability_grows_with_answers_and_recent_weigh_more(self):
        self.assertLess(situations.score_situations([resp()] * 2).reliability, situations.score_situations([resp()] * 6).reliability)
        low, high = resp(ladder=1, reaction=0, tradeoff=0), resp(ladder=5, reaction=3, tradeoff=3)
        self.assertGreater(situations.score_situations([low, low, low, high]).score,
                           situations.score_situations([high, low, low, low]).score)

    def test_only_last_answers_are_kept(self):
        r = situations.score_situations([resp()] * (config.SITUATION_MAX_KEPT + 5))
        self.assertEqual(r.n_answered, config.SITUATION_MAX_KEPT)

    def test_scenario_texts_do_not_depend_on_asset_numbers(self):
        a = situations.scenario_texts("NVIDIA", "NVDA", 2000)
        b = situations.scenario_texts("Obligations", "XBB.TO", 2000)
        self.assertEqual([l["level"] for l in a["ladder"]["levels"]], list(config.SITUATION_LADDER_LEVELS))
        self.assertEqual(a["reaction"]["text"], b["reaction"]["text"])


def _trade(day, side, amount, ticker="SPY"):
    return Trade(day, ticker, side, 1.0, 1.0, amount)


class LossEnduredTests(unittest.TestCase):
    D0 = date(2024, 1, 1)

    def series(self, path):
        rows = []
        for i, idx in enumerate(path):
            rows.append({"date": self.D0 + timedelta(days=i), "value": 1000.0 * idx, "flow": 0.0, "ret": 0.0, "index": idx})
        return rows

    def test_held_through_a_30_percent_drop_scores_high(self):
        series = self.series([1.0, 0.9, 0.7, 0.8, 1.0, 1.0])
        eps = history_v2._loss_episodes(series, [])
        self.assertEqual(len(eps), 1)
        self.assertAlmostEqual(eps[0]["max_depth"], 0.3)
        ind = history_v2._loss_endured_indicator(series, [], self.D0 + timedelta(days=5))
        self.assertAlmostEqual(ind.score, metrics.interpolate(30.0, config.ASSET_DRAWDOWN_ANCHORS), places=3)

    def test_selling_in_the_drop_scores_lower_than_holding(self):
        series = self.series([1.0, 0.9, 0.7, 0.8, 1.0, 1.0])
        sale = [_trade(self.D0 + timedelta(days=1), "sell", 450.0)]            # vend la moitié à -10 %
        held = history_v2._loss_endured_indicator(series, [], self.D0 + timedelta(days=5)).score
        sold = history_v2._loss_endured_indicator(series, sale, self.D0 + timedelta(days=5)).score
        self.assertLess(sold, held)

    def test_no_episode_means_unavailable_not_zero(self):
        ind = history_v2._loss_endured_indicator(self.series([1.0, 1.02, 1.05, 1.04]), [], self.D0 + timedelta(days=3))
        self.assertFalse(ind.available)

    def test_recency_half_life(self):
        self.assertAlmostEqual(history_v2._decay(0), 1.0)
        self.assertAlmostEqual(history_v2._decay(config.RECENCY_HALF_LIFE_DAYS), 0.5)


class CombineV2Tests(unittest.TestCase):
    @staticmethod
    def hist(score, n=20, cov=1.0, span=400):
        return HistoryResult(score, cov, n, [], [], span)

    def sit(self, score=50.0, n=6):
        return situations.SituationResult(score, n, 6, 1.0, min(1.0, n / 6), [], [])

    def test_weights_sum_to_one_and_follow_base(self):
        c = combine.combine_scores_v2(self.hist(40), self.sit(60))
        w = c["components"]
        self.assertAlmostEqual(w["history"]["effective_weight"] + w["situations"]["effective_weight"], 1.0)
        self.assertAlmostEqual(w["history"]["effective_weight"], config.HISTORY_WEIGHT_BASE_V2)
        self.assertAlmostEqual(c["final_score"], 0.6 * 40 + 0.4 * 60)

    def test_poor_history_gives_weight_to_situations(self):
        rich = combine.combine_scores_v2(self.hist(40, n=20), self.sit(60))["components"]["history"]["effective_weight"]
        poor = combine.combine_scores_v2(self.hist(40, n=3, span=30), self.sit(60))["components"]["history"]["effective_weight"]
        self.assertLess(poor, rich)

    def test_single_pillar_and_no_pillar(self):
        only_h = combine.combine_scores_v2(self.hist(40), situations.SituationResult(None, 0, 6))
        self.assertAlmostEqual(only_h["final_score"], 40)
        only_s = combine.combine_scores_v2(HistoryResult(None, 0.0, 0, [], [], 0), self.sit(70))
        self.assertAlmostEqual(only_s["final_score"], 70)
        with self.assertRaises(ValueError):
            combine.combine_scores_v2(HistoryResult(None, 0.0, 0, [], [], 0), situations.SituationResult(None, 0, 6))

    def test_gap_widens_margin_and_is_flagged(self):
        agree = combine.combine_scores_v2(self.hist(50), self.sit(52))
        apart = combine.combine_scores_v2(self.hist(30), self.sit(80))
        self.assertGreater(apart["uncertainty"]["margin"], agree["uncertainty"]["margin"])
        self.assertTrue(any("Écart notable" in w for w in apart["warnings"]))
        self.assertEqual(agree["warnings"], [])
        self.assertLess(agree["uncertainty"]["low"], agree["final_score"] + 1e-9)

    def test_margin_formula(self):
        c = combine.combine_scores_v2(self.hist(30), self.sit(80))
        expected = config.VERDICT_MAX_UNCERTAINTY_MARGIN * (1 - c["confidence"]["value"]) + \
            config.TOLERANCE_MARGIN_GAP_COEF * (50 - config.TOLERANCE_MARGIN_GAP_FREE)
        self.assertAlmostEqual(c["uncertainty"]["margin"], expected)


class ProfileV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = {n: combine.compute_user_profile(**a, model_version="v2") for n, a in personas.all_personas().items()}

    def test_default_version_is_v2_and_v1_still_available(self):
        self.assertEqual(config.SCORE_MODEL_VERSION, "v2")
        a = personas.all_personas()["mateo"]
        self.assertEqual(combine.compute_user_profile(**a)["model"]["version"], "v2")
        self.assertEqual(combine.compute_user_profile(**a, model_version="v1")["model"]["version"], "v1")
        with self.assertRaises(ValueError):
            combine.compute_user_profile(**a, model_version="v9")

    def test_personas_are_ordered(self):
        s = {n: p["final_score"] for n, p in self.profiles.items()}
        self.assertLess(s["robert"], s["mateo"])
        self.assertLess(s["mateo"], s["amira"])
        h = {n: p["history"]["score"] for n, p in self.profiles.items() if p["history"]["score"] is not None}
        self.assertEqual(set(h), {"amira", "mateo", "robert"})                  # Léa : aucun historique
        self.assertGreater(h["amira"], max(h["mateo"], h["robert"]))
        # Sur l'historique seul, Robert dépasse Mateo (6 positions seulement : concentration du risque élevée).

    def test_decomposition_adds_up(self):
        for n, p in self.profiles.items():
            comps = p["components"]
            self.assertAlmostEqual(sum(c["contribution"] for c in comps.values()), p["final_score"], places=2, msg=n)
            avail = [i for i in p["history"]["indicators"] if i["available"]]
            if p["history"]["score"] is not None:
                self.assertAlmostEqual(sum(i["contribution"] for i in avail), p["history"]["score"], places=2, msg=n)
                self.assertAlmostEqual(sum(i["effective_weight"] for i in avail), 1.0, places=3, msg=n)
            self.assertAlmostEqual(sum(config.HISTORY_V2_WEIGHTS.values()), 1.0)

    def test_repeatable_and_input_order_independent(self):
        a = personas.all_personas()["amira"]
        first = json.dumps(combine.compute_user_profile(**a), sort_keys=True)
        shuffled = dict(a, transactions=list(reversed(a["transactions"])))
        self.assertEqual(first, json.dumps(combine.compute_user_profile(**shuffled), sort_keys=True))

    def test_uncertainty_interval_contains_score(self):
        for p in self.profiles.values():
            u = p["uncertainty"]
            self.assertLessEqual(u["low"], p["final_score"])
            self.assertGreaterEqual(u["high"], p["final_score"])

    def test_risky_purchase_raises_and_safe_purchase_lowers_score(self):
        with tempfile.TemporaryDirectory() as d:
            base = service.build_profile("mateo", Path(d))["final_score"]
            service.simulate_purchase("mateo", "BTC-USD", 50000, Path(d))
            up = service.build_profile("mateo", Path(d))["final_score"]
        with tempfile.TemporaryDirectory() as d:
            service.simulate_purchase("mateo", "ZST.TO", 50000, Path(d))
            down = service.build_profile("mateo", Path(d))["final_score"]
        self.assertGreater(up, base)
        self.assertLess(down, base)

    def test_answers_move_the_score_in_the_right_direction(self):
        a = personas.all_personas()["mateo"]
        bold = combine.compute_user_profile(**dict(a, situations_answers=[resp(ladder=5, reaction=3, tradeoff=3)] * 6))
        shy = combine.compute_user_profile(**dict(a, situations_answers=[resp(ladder=0, reaction=0, tradeoff=0)] * 6))
        self.assertGreater(bold["final_score"], shy["final_score"])

    def test_portfolio_series_treats_a_purchase_as_flow_not_gain(self):
        a = personas.all_personas()["mateo"]
        from agent_risque.transactions import Transaction, validate_and_sort
        trades, _ = validate_and_sort(a["transactions"], AS_OF)
        rows = history_v2.portfolio_series(trades, AS_OF)
        self.assertIsNone(rows[0]["ret"])
        first_buy_day = [r for r in rows if r["flow"] > 0][1]
        self.assertLess(abs(first_buy_day["ret"]), 0.2)               # un gros achat ne crée pas un rendement géant

    def test_report_names_the_new_pillar(self):
        from agent_risque.report.facts import build_fact_sheet
        from agent_risque import asset_score, comparison
        p = self.profiles["mateo"]
        asset = asset_score.score_asset("QQQ", AS_OF)
        sheet = build_fact_sheet(comparison.compare(p, asset, 2000), p, asset, "intermediaire")
        text = " ".join(f.text for f in sheet.facts)
        self.assertIn("mises en situation", text)
        self.assertNotIn("quiz", text.lower())


class WebFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.srv = server.make_server(0, "template", cls.dir, ask_situations=True)
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, path, data=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if data is not None else "GET",
                                   data=urllib.parse.urlencode(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(r) as resp_:
                return resp_.status, resp_.read().decode("utf-8"), resp_.geturl()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), exc.geturl()

    def full_answers(self, ticker, **extra):
        data = {"u": "mateo", "ticker": ticker, "amount": "2000", "reaction": "2", "action": "answer"}
        data.update({f"ladder_{i}": "oui" if i < 2 else "non" for i in range(3)})
        data.update({f"tradeoff_{i}": "oui" if i < 1 else "non" for i in range(3)})
        data.update(extra)
        return data

    def test_first_visit_asks_then_shows_verdict_and_does_not_ask_again(self):
        status, html, url = self.req("/asset/MSFT?u=mateo&amount=2000")
        self.assertIn("/asset/MSFT", url)                                  # même adresse : c'est un pop-up
        self.assertIn('role="dialog"', html)
        self.assertIn("Avant le verdict", html)
        self.assertNotIn("Simuler un achat", html)                         # le verdict n'est pas rendu derrière
        self.assertNotIn("Verdict", html.split("<h2 id=\"m-title\">")[0])
        status, html, url = self.req("/situation", self.full_answers("MSFT"))
        self.assertIn("/asset/MSFT", url)
        self.assertNotIn('role="dialog"', html)
        self.assertIn("Simuler un achat", html)
        self.assertEqual(len(situation_ledger.load("fictif_mateo", self.dir)), 1)
        status, html, url = self.req("/asset/MSFT?u=mateo&amount=2000")
        self.assertNotIn('role="dialog"', html)                            # plus de question pour cette action

    def test_amount_is_asked_before_the_popup(self):
        status, html, _ = self.req("/asset/JNJ?u=lea")                      # pas de montant : étape « montant » d'abord
        self.assertNotIn('role="dialog"', html)
        self.assertIn('name="amount"', html)
        self.assertIn("Continuer", html)
        status, html, _ = self.req("/asset/JNJ?u=lea&amount=3500")          # montant saisi : le pop-up le reprend
        self.assertIn('role="dialog"', html)
        self.assertIn("3 500", html)

    def test_ladder_has_three_scenarios(self):
        self.assertEqual(len(config.SITUATION_LADDER_LEVELS), 3)
        _, html, _ = self.req("/asset/JNJ?u=lea&amount=2000")
        self.assertEqual(html.count('name="ladder_'), 6)                   # 3 lignes × (oui, non)

    def test_skip_is_allowed_and_not_scored(self):
        before = service.build_profile("robert", self.dir)["situations"]["n_answered"]
        status, html, url = self.req("/situation", {"u": "robert", "ticker": "SPY", "amount": "2000", "action": "skip"})
        self.assertIn("/asset/SPY", url)
        self.assertEqual(service.build_profile("robert", self.dir)["situations"]["n_answered"], before)
        self.assertFalse(service.needs_situation("robert", "SPY", self.dir))

    def test_incomplete_answers_are_refused_with_a_message(self):
        data = self.full_answers("AAPL")
        del data["reaction"]
        status, html, _ = self.req("/situation", data)
        self.assertIn("Répondez à chaque question", html)
        self.assertEqual([r for r in situation_ledger.load("fictif_mateo", self.dir) if r["ticker"] == "AAPL"], [])

    def test_answers_change_the_profile(self):
        base = service.build_profile("amira", self.dir)["final_score"]
        self.req("/situation", {"u": "amira", "ticker": "NVDA", "amount": "2000", "action": "answer", "reaction": "0",
                                **{f"ladder_{i}": "non" for i in range(3)}, **{f"tradeoff_{i}": "non" for i in range(3)}})
        self.assertLess(service.build_profile("amira", self.dir)["final_score"], base)

    def test_reset_clears_situations_too(self):
        self.req("/reinitialiser", {"u": "mateo"})
        self.assertEqual(situation_ledger.load("fictif_mateo", self.dir), [])


if __name__ == "__main__":
    unittest.main()
