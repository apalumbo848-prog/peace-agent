"""Tests de l'étape 5 : registre d'achats, serveur local, agent de suivi (faux agent, aucun appel réseau)."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from agent_risque import config
from agent_risque.agent import followup, tools
from agent_risque.app import ledger, server, service

AS_OF = service.AS_OF


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_record_load_reset(self):
        entry = ledger.record_purchase("fictif_mateo", "QQQ", 2000, AS_OF, self.dir)
        self.assertEqual(entry["side"], "buy")
        self.assertAlmostEqual(entry["amount_cad"], 2000, delta=2)       # arrondi à 4 décimales de quantité
        self.assertEqual(len(ledger.load("fictif_mateo", self.dir)), 1)
        ledger.reset("fictif_mateo", self.dir)
        self.assertEqual(ledger.load("fictif_mateo", self.dir), [])

    def test_same_input_same_file(self):
        other = Path(tempfile.mkdtemp())
        for d in (self.dir, other):
            ledger.record_purchase("fictif_mateo", "QQQ", 2000, AS_OF, d)
        a = (self.dir / "fictif_mateo_achats_simules.json").read_bytes()
        b = (other / "fictif_mateo_achats_simules.json").read_bytes()
        self.assertEqual(a, b)

    def test_rejects_bad_input(self):
        for amount in (0, -5, float("nan"), config.APP_MAX_AMOUNT_CAD * 2):
            with self.assertRaises(ledger.LedgerError):
                ledger.quote("QQQ", amount, AS_OF)
        with self.assertRaises(ledger.LedgerError):
            ledger.quote("PASUNTITRE", 100, AS_OF)
        with self.assertRaises(ledger.LedgerError):
            ledger.load("../evil", self.dir)                              # identifiant de fichier non sûr
        with self.assertRaises(ledger.LedgerError):
            ledger.quote("QQQ", 100, date(2026, 11, 14))                  # pas de prix ce jour-là

    def test_purchase_changes_profile_deterministically(self):
        base = service.build_profile("mateo", self.dir)
        service.simulate_purchase("mateo", "ZST.TO", 50000, self.dir)
        after = service.build_profile("mateo", self.dir)
        self.assertNotEqual(base["final_score"], after["final_score"])
        self.assertEqual(after, service.build_profile("mateo", self.dir))   # mêmes entrées = même profil


class ParseAmountTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(server.parse_amount("2000"), 2000)
        self.assertEqual(server.parse_amount("2 000,50"), 2000.5)

    def test_invalid(self):
        for raw in ("", None, "-5", "abc", "0", "1e9", "99999999999", "2000,555", "<script>"):
            with self.assertRaises(server.BadRequest, msg=raw):
                server.parse_amount(raw)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.srv = server.make_server(0, "template", cls.dir, ask_situations=False)
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def request(self, path, data=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if data is not None else "GET",
                                     data=urllib.parse.urlencode(data).encode() if data is not None else None,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode("utf-8"), r.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), exc.headers

    def test_pages_and_security_headers(self):
        status, html, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("<script", html.lower())
        self.assertEqual(self.request("/?u=inconnu")[0], 400)
        self.assertEqual(self.request("/asset/PASUNTITRE?u=mateo")[0], 400)
        self.assertEqual(self.request("/nimporte")[0], 404)

    def test_asset_page_is_deterministic_and_has_agent_sections(self):
        a = self.request("/asset/QQQ?u=mateo&amount=2000")[1]
        b = self.request("/asset/QQQ?u=mateo&amount=2000")[1]
        self.assertEqual(a, b)
        for needle in ("Simuler un achat", "Pourquoi ?", "Comment ce résultat a été calculé", "aucune transaction réelle"):
            self.assertIn(needle, a)

    def test_bad_amount_is_reported_not_crashing(self):
        status, html, _ = self.request("/asset/QQQ?u=mateo&amount=abc")
        self.assertEqual(status, 200)
        self.assertIn("Montant invalide", html)

    def test_preset_answers(self):
        for q in ("why", "profile", "scenario"):
            status, html, _ = self.request(f"/asset/QQQ?u=mateo&amount=2000&q={q}")
            self.assertEqual(status, 200)
            self.assertIn("Réponse préparée, sans IA", html)

    def test_layout_verdict_then_purchase_then_more_and_no_checkbox(self):
        status, html, _ = self.request("/asset/NVDA?u=robert&amount=2000")
        self.assertEqual(status, 200)
        self.assertNotIn('type="checkbox"', html)
        i_badge, i_buy, i_more = html.index('class="badge'), html.index('id="achat"'), html.index('id="en-savoir-plus"')
        self.assertLess(i_badge, i_buy)
        self.assertLess(i_buy, i_more)
        self.assertIn("En savoir plus", html)
        self.assertNotIn("<details class=\"more\" id=\"en-savoir-plus\" open", html)
        self.assertGreater(html.index("Comment ce résultat a été calculé"), i_more)   # le détail est dans le repli
        _, html2, _ = self.request("/asset/NVDA?u=robert&amount=2000&q=why")
        self.assertIn('id="en-savoir-plus" open', html2)

    def test_red_purchase_is_recorded_without_checkbox(self):
        data = {"u": "amira", "ticker": "NVDA", "amount": "5000000"}
        status, html, _ = self.request("/achat", data)
        self.assertEqual(status, 200)
        self.assertIn("Achat simulé enregistré", html)
        self.assertEqual(len(ledger.load("fictif_amira", self.dir)), 1)
        self.request("/reinitialiser", {"u": "amira"})

    def test_cross_origin_post_refused(self):
        status, _, _ = self.request("/achat", {"u": "mateo", "ticker": "QQQ", "amount": "100"},
                                    headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(ledger.load("fictif_mateo", self.dir), [])

    def test_html_is_escaped(self):
        # la question n'est pas publiée telle quelle ; un conseil demandé reçoit le refus fixe sans appel au modèle
        status, html, _ = self.request("/question", {"u": "mateo", "ticker": "QQQ", "amount": "2000",
                                                      "question": "<img src=x onerror=1> dois-je acheter ?"})
        self.assertEqual(status, 200)
        self.assertNotIn("<img src=x", html)
        self.assertIn("Refus", html)


class FakeAgent:
    """Joue le rôle de l'agent Strands : appelle les vrais outils puis renvoie un JSON choisi."""

    def __init__(self, ctx, answers):
        self.ctx, self.answers, self.calls = ctx, list(answers), 0

    def __call__(self, prompt):
        self.calls += 1
        tools.get_facts(self.ctx, "en_bref")
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class FollowupTests(unittest.TestCase):
    def setUp(self):
        c = service.open_asset_page("mateo", "QQQ", 2000, Path(tempfile.mkdtemp()))
        r = service.report_for(c)
        self.ctx = tools.FollowupContext(r["sheet"], c.verdict, c.profile, c.asset, c.amount_cad)
        self.headline = r["sheet"].by_key()
        self.f1 = r["sheet"].facts[0]

    def good(self):
        return json.dumps({"sentences": [{"text": self.f1.text, "facts": [self.f1.id]}]})

    def test_advice_refused_without_calling_model(self):
        def factory(ctx):
            raise AssertionError("le modèle ne doit pas être appelé")
        for q in ("Dois-je acheter cette action ?", "Tu me conseilles quoi ?", "Je devrais vendre ?"):
            self.assertEqual(followup.ask_free(self.ctx, q, factory)["kind"], "refus", q)

    def test_invalid_questions(self):
        self.assertEqual(followup.ask_free(self.ctx, "   ")["kind"], "invalide")
        self.assertEqual(followup.ask_free(self.ctx, "x" * 400)["kind"], "invalide")

    def test_verified_answer_accepted_and_logged(self):
        agent = FakeAgent(self.ctx, [self.good()])
        out = followup.ask_free(self.ctx, "Pourquoi ce verdict ?", lambda c: agent)
        self.assertEqual(out["kind"], "agent")
        self.assertEqual(out["tool_log"][0]["tool"], "get_facts")

    def test_invented_number_rejected_then_retry_succeeds(self):
        bad = json.dumps({"sentences": [{"text": "Le score est de 77 sur 100.", "facts": [self.f1.id]}]})
        agent = FakeAgent(self.ctx, [bad, self.good()])
        out = followup.ask_free(self.ctx, "Pourquoi ?", lambda c: agent)
        self.assertEqual(out["kind"], "agent")
        self.assertEqual(agent.calls, 2)

    def test_always_bad_falls_back_without_showing_model_text(self):
        bad = json.dumps({"sentences": [{"text": "Achetez maintenant, c'est garanti.", "facts": ["F1"]}]})
        agent = FakeAgent(self.ctx, [bad])
        out = followup.ask_free(self.ctx, "Pourquoi ?", lambda c: agent)
        self.assertEqual(out["kind"], "echec")
        self.assertEqual(out["sentences"][0]["text"], config.FOLLOWUP_FAILURE_FR)

    def test_unknown_fact_and_missing_citation_rejected(self):
        for payload in ({"sentences": [{"text": "Texte.", "facts": ["F999"]}]},
                        {"sentences": [{"text": "Texte sans citation.", "facts": []}]},
                        {"sentences": []}):
            self.assertTrue(followup.verify_answer(followup._parse(json.dumps(payload)), self.ctx))

    def test_agent_unavailable_gives_failure_not_crash(self):
        def factory(ctx):
            raise ImportError("strands absent")
        self.assertEqual(followup.ask_free(self.ctx, "Pourquoi ?", factory)["kind"], "echec")

    def test_scenario_tool_creates_cited_facts_and_numbers_are_allowed(self):
        tools.recompute_with_amount(self.ctx, 500)
        sid = self.ctx.extra_facts[0].id
        ok = [{"text": self.ctx.extra_facts[0].text, "facts": [sid]}]
        self.assertEqual(followup.verify_answer(ok, self.ctx), [])
        self.assertIn("Montant invalide", tools.recompute_with_amount(self.ctx, -3))
        self.assertIn("Terme inconnu", tools.explain_term(self.ctx, "zzz"))

    def test_scenario_does_not_change_profile_or_asset(self):
        before = json.dumps(self.ctx.profile, sort_keys=True)
        tools.recompute_with_amount(self.ctx, 100000)
        self.assertEqual(before, json.dumps(self.ctx.profile, sort_keys=True))


class LeadSentenceTests(unittest.TestCase):
    """La phrase sous le badge doit dire POURQUOI : risque seul ou contrainte déclarée."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp()
        cls.server = server.make_server(0, "template", Path(cls.dir), ask_situations=False)
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def lead(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        return conn.getresponse().read().decode()

    def test_constraint_driven_red_is_explained(self):
        html = self.lead("/asset/ENB.TO?u=mateo&amount=2000")                 # risque vert, exclusion Énergie -> rouge
        self.assertIn("en accord avec votre tolérance", html)
        self.assertIn("contraintes déclarées relève aussi le verdict", html)
        self.assertIn("Verdict rouge", html)

    def test_pure_risk_red_has_no_constraint_sentence(self):
        html = self.lead("/asset/TSLA?u=robert&amount=2000")                 # rouge par le risque seul
        self.assertNotIn("contraintes déclarées relève", html)


if __name__ == "__main__":
    unittest.main()
