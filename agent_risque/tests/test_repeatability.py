"""Répétabilité : mêmes entrées = mêmes scores, toujours (et même fichier JSON)."""

import random
import tempfile
import unittest
from pathlib import Path

from agent_risque import combine, profile_store
from agent_risque.fixtures import personas


class RepeatabilityTests(unittest.TestCase):
    def test_same_profile_same_score(self):
        for name, args in personas.all_personas().items():
            with self.subTest(persona=name):
                first = combine.compute_user_profile(**args)
                second = combine.compute_user_profile(**args)
                self.assertEqual(first, second)
                self.assertEqual(profile_store.dumps(first), profile_store.dumps(second))

    def test_order_of_transactions_does_not_matter(self):
        for name, args in personas.all_personas().items():
            with self.subTest(persona=name):
                shuffled = dict(args)
                txs = list(args["transactions"])
                random.Random(12345).shuffle(txs)   # hasard uniquement dans le TEST, jamais dans le calcul
                shuffled["transactions"] = txs
                reference = combine.compute_user_profile(**args)
                other = combine.compute_user_profile(**shuffled)
                self.assertEqual(reference["final_score"], other["final_score"])
                self.assertEqual(reference, other)

    def test_saved_file_is_identical_across_runs(self):
        args = personas.all_personas()["mateo"]
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            p1 = profile_store.save_profile(combine.compute_user_profile(**args), Path(d1))
            p2 = profile_store.save_profile(combine.compute_user_profile(**args), Path(d2))
            self.assertEqual(p1.read_bytes(), p2.read_bytes())

    def test_resaving_same_as_of_keeps_one_history_entry(self):
        args = personas.all_personas()["robert"]
        with tempfile.TemporaryDirectory() as d:
            profile = combine.compute_user_profile(**args)
            profile_store.save_profile(profile, Path(d))
            profile_store.save_profile(profile, Path(d))
            loaded = profile_store.load_profile(Path(d), profile["user_id"])
            self.assertEqual(len(loaded["score_history"]), 1)
            self.assertEqual(loaded["final_score"], profile["final_score"])


if __name__ == "__main__":
    unittest.main()
