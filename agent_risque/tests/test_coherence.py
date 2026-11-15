"""Cohérence : profil robert = score bas, amira = score élevé, monotonie, décomposition."""

import math
import unittest
from datetime import date

from agent_risque import combine, config, history_score, quiz
from agent_risque.fixtures import personas
from agent_risque.transactions import Transaction, validate_and_sort


def setUpModule():
    config.SCORE_MODEL_VERSION = "v1"     # ces tests décrivent la mécanique du modèle v1 (quiz) ; v2 : test_model_v2.py


def tearDownModule():
    config.SCORE_MODEL_VERSION = "v2"


# Seuils de ces tests : hypothèses à valider avec l'équipe (voir la proposition, point 9).
PRUDENT_MAX = 35.0
AUDACIOUS_MIN = 65.0


def _profiles():
    return {n: combine.compute_user_profile(**a) for n, a in personas.all_personas().items()}


class CoherenceTests(unittest.TestCase):
    def test_prudent_low_balanced_middle_bold_high(self):
        p = _profiles()
        self.assertLessEqual(p["robert"]["final_score"], PRUDENT_MAX)
        self.assertGreaterEqual(p["amira"]["final_score"], AUDACIOUS_MIN)
        self.assertLess(p["robert"]["final_score"], p["mateo"]["final_score"])
        self.assertLess(p["mateo"]["final_score"], p["amira"]["final_score"])

    def test_history_and_quiz_each_ordered(self):
        p = _profiles()
        # Quiz : ordre complet. Historique : Amira est la plus élevée ; Robert (peu de positions, donc concentration)
        # dépasse Mateo sur l'historique seul : constat documenté, le score FINAL reste dans l'ordre attendu.
        self.assertLess(p["robert"]["quiz"]["score"], p["mateo"]["quiz"]["score"])
        self.assertLess(p["mateo"]["quiz"]["score"], p["amira"]["quiz"]["score"])
        self.assertGreater(p["amira"]["history"]["score"], max(p["mateo"]["history"]["score"], p["robert"]["history"]["score"]))

    def test_scores_stay_in_range(self):
        for name, prof in _profiles().items():
            with self.subTest(persona=name):
                self.assertGreaterEqual(prof["final_score"], 0.0)
                self.assertLessEqual(prof["final_score"], 100.0)

    def test_quiz_extremes(self):
        lowest = {q["id"]: 0 for q in config.QUIZ_QUESTIONS}
        highest = {q["id"]: len(q["answers"]) - 1 for q in config.QUIZ_QUESTIONS}
        self.assertEqual(quiz.score_quiz(lowest).score, 0.0)
        self.assertEqual(quiz.score_quiz(highest).score, 100.0)

    def test_volatility_indicator_is_monotonic(self):
        as_of = date(2026, 11, 12)
        scores = []
        for ticker in ("ZST.TO", "SPY", "NVDA", "ETH-USD"):
            trades, _ = validate_and_sort([Transaction(date(2025, 6, 2), ticker, "buy", 10)], as_of)
            ind = history_score._volatility_indicator(trades, [])
            self.assertTrue(ind.available, ticker)
            scores.append(ind.score)
        self.assertEqual(scores, sorted(scores))
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])

    def test_decomposition_adds_up(self):
        for name, prof in _profiles().items():
            with self.subTest(persona=name):
                parts = prof["components"]
                self.assertAlmostEqual(
                    parts["history"]["contribution"] + parts["quiz"]["contribution"],
                    prof["final_score"], places=3)
                if prof["history"]["score"] is not None:                    # Léa n'a aucun historique
                    self.assertAlmostEqual(
                        sum(i["contribution"] for i in prof["history"]["indicators"]),
                        prof["history"]["score"], places=3)
                self.assertAlmostEqual(
                    sum(i["contribution"] for i in prof["quiz"]["items"]),
                    prof["quiz"]["score"], places=3)
                self.assertAlmostEqual(
                    parts["history"]["effective_weight"] + parts["quiz"]["effective_weight"], 1.0, places=3)

    def test_few_transactions_give_quiz_more_weight(self):
        args = personas.all_personas()["mateo"]
        few = dict(args, transactions=args["transactions"][:3])
        full = combine.compute_user_profile(**args)
        small = combine.compute_user_profile(**few)
        self.assertEqual(full["components"]["quiz"]["effective_weight"] < 0.5 + 1e-9, True)
        self.assertGreater(small["components"]["quiz"]["effective_weight"], 0.5)
        self.assertLess(small["confidence"]["value"], full["confidence"]["value"])

    def test_no_history_means_quiz_only(self):
        args = dict(personas.all_personas()["robert"], transactions=[])
        prof = combine.compute_user_profile(**args)
        self.assertEqual(prof["components"]["history"]["effective_weight"], 0.0)
        self.assertEqual(prof["final_score"], prof["quiz"]["score"])
        self.assertEqual(prof["confidence"]["label"], "faible")

    def test_divergence_between_history_and_quiz_is_flagged(self):
        args = personas.all_personas()["amira"]
        args = dict(args, quiz_answers=personas.all_personas()["robert"]["quiz_answers"])
        prof = combine.compute_user_profile(**args)
        self.assertTrue(any("Écart notable" in w for w in prof["warnings"]))
        self.assertLess(prof["confidence"]["parts"]["agreement"], 1.0)

    def test_nothing_to_score_raises(self):
        with self.assertRaises(ValueError):
            combine.compute_user_profile("vide", date(2026, 11, 12), [], {})

    def test_more_risk_never_lowers_the_history_score(self):
        """Ajouter une grosse position en NVDA ne doit pas baisser le score d'un profil robert."""
        args = personas.all_personas()["robert"]
        base = combine.compute_user_profile(**args)
        extra = list(args["transactions"]) + [Transaction(date(2026, 6, 2), "NVDA", "buy", 400)]
        risky = combine.compute_user_profile(**dict(args, transactions=extra))
        self.assertGreater(risky["history"]["score"], base["history"]["score"])


if __name__ == "__main__":
    unittest.main()
