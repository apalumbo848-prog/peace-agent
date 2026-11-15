"""Étape 4 : fiche de faits, texte fixe, vérificateur, reformulation (faux client), graphiques, HTML."""

import copy
import json
import re
import tempfile
import unittest
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from agent_risque import asset_score, combine, comparison, config, constraints, data_access
from agent_risque.fixtures import personas
from agent_risque.report import charts, facts, llm_text, render_html, verify
from agent_risque.report.build import build_report

AS_OF = date(2026, 11, 12)
PROFILES = {n: combine.compute_user_profile(**a) for n, a in personas.all_personas().items()}
ASSETS = {t: asset_score.score_asset(t, AS_OF) for t in data_access.load_universe()}
UNIVERSE = {t: a.score for t, a in ASSETS.items()}
CASES = [("robert", "TSLA", None), ("robert", "BTC-USD", None), ("mateo", "QQQ", 2000),
         ("amira", "ZST.TO", None), ("amira", "NVDA", 5_000_000), ("mateo", "SPY", None)]


def _verdict(persona, ticker, amount=None):
    return comparison.compare(PROFILES[persona], ASSETS[ticker], amount)


def _sheet(persona, ticker, amount=None, level=None):
    level = level or constraints.parse_declared(PROFILES[persona]["inputs"]["declared_not_scored"])[0].experience
    return facts.build_fact_sheet(_verdict(persona, ticker, amount), PROFILES[persona], ASSETS[ticker], level)


class FakeClient:
    """Faux client Bedrock : renvoie des réponses prévues, sans réseau."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return {"output": {"message": {"content": [{"text": response}]}}}


def _llm_json_from_template(sheet, mutate=None):
    """Réponse JSON 'idéale' construite à partir du texte fixe, éventuellement altérée."""
    report = build_report(_verdict("mateo", "QQQ", 2000), PROFILES["mateo"], ASSETS["QQQ"], mode="template")["report"]
    data = {"sections": [{"id": s["id"], "sentences": s["sentences"]} for s in report["sections"]]}
    if mutate:
        mutate(data)
    return json.dumps(data, ensure_ascii=False)


class FactTests(unittest.TestCase):
    def test_sheet_is_deterministic_and_ids_sequential(self):
        a, b = _sheet("mateo", "QQQ"), _sheet("mateo", "QQQ")
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual([f.id for f in a.facts], [f"F{i}" for i in range(1, len(a.facts) + 1)])

    def test_key_numbers_come_from_the_verdict(self):
        for persona, ticker, amount in CASES:
            v = _verdict(persona, ticker, amount)
            sheet = _sheet(persona, ticker, amount)
            text = " ".join(f.text for f in sheet.facts)
            with self.subTest(case=(persona, ticker)):
                self.assertIn(facts.fr(v["asset"]["score"], 0), text)
                self.assertIn(facts.fr(v["user"]["effective_tolerance"], 0), text)
                self.assertIn(v["risk_color"], text)

    def test_every_fact_has_type_and_source_and_is_short(self):
        for persona, ticker, amount in CASES:
            for f in _sheet(persona, ticker, amount).facts:
                with self.subTest(fact=f.key):
                    self.assertIn(f.type, facts.TYPES)
                    self.assertTrue(f.source)
                    if not f.key.startswith("limit_") and not f.key.startswith("constraint_"):
                        self.assertLessEqual(len(f.text.split()), config.REPORT_MAX_SENTENCE_WORDS)

    def test_french_number_format(self):
        self.assertEqual(facts.fr(28.14, 1), "28,1")
        self.assertEqual(facts.fr(3.0, 0, True), "+3")
        self.assertEqual(facts.fr(-0.04, 1), "0,0")
        self.assertEqual(facts.fr(-12.5, 1), "-12,5")


class TemplateReportTests(unittest.TestCase):
    def test_template_is_deterministic_and_passes_verification(self):
        for persona, ticker, amount in CASES:
            r1 = build_report(_verdict(persona, ticker, amount), PROFILES[persona], ASSETS[ticker])
            r2 = build_report(_verdict(persona, ticker, amount), PROFILES[persona], ASSETS[ticker])
            with self.subTest(case=(persona, ticker)):
                self.assertEqual(r1["report"], r2["report"])
                self.assertEqual(verify.verify_report(r1["report"], r1["sheet"]), [])
                self.assertEqual(r1["meta"]["mode"], "template")

    def test_levels_change_the_detail_but_not_the_verdict(self):
        v, p, a = _verdict("mateo", "QQQ", 2000), PROFILES["mateo"], ASSETS["QQQ"]
        words = {}
        for level in config.REPORT_LEVELS:
            res = build_report(v, p, a, level=level)
            words[level] = sum(len(s["text"].split()) for sec in res["report"]["sections"] for s in sec["sentences"])
            self.assertLessEqual(words[level], config.REPORT_MAX_WORDS[level])
            self.assertEqual(verify.verify_report(res["report"], res["sheet"]), [])
            self.assertIn("jaune", " ".join(s["text"] for sec in res["report"]["sections"] for s in sec["sentences"]))
        self.assertLess(words["debutant"], words["intermediaire"])
        self.assertLess(words["intermediaire"], words["avance"])

    def test_level_comes_from_declared_experience(self):
        self.assertEqual(build_report(_verdict("robert", "SPY"), PROFILES["robert"], ASSETS["SPY"])["level"], "avance")
        self.assertEqual(build_report(_verdict("mateo", "SPY"), PROFILES["mateo"], ASSETS["SPY"])["level"], "intermediaire")
        args = dict(personas.all_personas()["robert"], declared={"experience": "expert"})
        p = combine.compute_user_profile(**args)
        res = build_report(comparison.compare(p, ASSETS["SPY"]), p, ASSETS["SPY"])
        self.assertEqual(res["level"], config.REPORT_DEFAULT_LEVEL)

    def test_plain_level_uses_simple_wording(self):
        sheet = _sheet("mateo", "QQQ", level="debutant")
        comp = next(f for f in sheet.facts if f.key == "component_volatility")
        self.assertNotIn("annualisée", comp.text_for("debutant"))
        self.assertIn("CVaR", next(f for f in sheet.facts if f.key == "component_tail_risk").text_for("avance"))

    def test_personas_scenarios(self):
        def text(persona, ticker, amount=None):
            res = build_report(_verdict(persona, ticker, amount), PROFILES[persona], ASSETS[ticker])
            return " ".join(s["text"] for sec in res["report"]["sections"] for s in sec["sentences"])
        self.assertIn("horizon", text("robert", "BTC-USD"))                       # Robert est contesté (horizon court)
        self.assertIn("ESG", text("mateo", "SPY"))                             # Mateo : ESG non vérifiable
        self.assertIn("bien plus prudente", text("amira", "ZST.TO"))           # Amira
        self.assertRegex(text("amira", "NVDA", 5_000_000), r"NVDA représenterait \d+% de votre portefeuille")   # concentration signalée

    def test_constraint_violations_always_present(self):
        res = build_report(_verdict("amira", "NVDA", 5_000_000), PROFILES["amira"], ASSETS["NVDA"], level="debutant")
        ids = {i for sec in res["report"]["sections"] for s in sec["sentences"] for i in s["facts"]}
        for f in res["sheet"].facts:
            if f.must_cite and f.min_level <= 0:
                self.assertIn(f.id, ids)


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.v, self.p, self.a = _verdict("mateo", "QQQ", 2000), PROFILES["mateo"], ASSETS["QQQ"]
        self.res = build_report(self.v, self.p, self.a)
        self.sheet = self.res["sheet"]

    def _check(self, mutate):
        report = copy.deepcopy(self.res["report"])
        mutate(report)
        return verify.verify_report(report, self.sheet, check_sentence_length=True)

    def test_clean_report_passes(self):
        self.assertEqual(self._check(lambda r: None), [])

    def test_invented_number_is_caught(self):
        errors = self._check(lambda r: r["sections"][0]["sentences"][1].update(text="Le risque de l'action est de 77 sur 100 [F3]."))
        self.assertTrue(any("Nombre absent" in e for e in errors))

    def test_rounded_number_is_accepted(self):
        fid = next(f.id for f in self.sheet.facts if "22,5" in f.text)      # volatilité de QQQ : 22,5 %
        errors = self._check(lambda r: r["sections"][3]["sentences"][2].update(
            text=f"L'action varie d'environ 23 % par an [{fid}]."))
        self.assertFalse(any("Nombre absent" in e for e in errors), errors)

    def test_unknown_citation_and_missing_citation(self):
        e1 = self._check(lambda r: r["sections"][0]["sentences"][0].update(facts=["F999"]))
        e2 = self._check(lambda r: r["sections"][0]["sentences"][0].update(facts=[]))
        self.assertTrue(any("inconnu" in e for e in e1))
        self.assertTrue(any("sans fait cité" in e for e in e2))

    def test_banned_phrases_are_caught(self):
        for phrase in ("Achetez maintenant cette action.", "Nous recommandons ce titre.", "Rendement garanti."):
            errors = self._check(lambda r, p=phrase: r["sections"][0]["sentences"].append({"text": p, "facts": ["F1"]}))
            with self.subTest(phrase=phrase):
                self.assertTrue(any("interdite" in e for e in errors))

    def test_foreign_ticker_and_date_are_caught(self):
        errors = self._check(lambda r: r["sections"][0]["sentences"].append(
            {"text": "AAPL a gagné depuis le 2020-01-01.", "facts": ["F1"]}))
        self.assertTrue(any("AAPL" in e for e in errors))
        self.assertTrue(any("2020-01-01" in e for e in errors))

    def test_missing_mandatory_fact_and_section(self):
        errors = self._check(lambda r: r["sections"][5]["sentences"].clear())
        self.assertTrue(any("obligatoire" in e for e in errors))
        errors = self._check(lambda r: r["sections"].pop())
        self.assertTrue(any("Sections attendues" in e for e in errors))

    def test_too_long_text_and_sentence(self):
        long_sentence = "mot " * 40 + "[F1]"
        errors = self._check(lambda r: r["sections"][0]["sentences"].append({"text": long_sentence, "facts": ["F1"]}))
        self.assertTrue(any("trop longue" in e for e in errors))
        filler = {"text": ("Le verdict est décrit. " * 5).strip() + " [F1]", "facts": ["F1"]}
        errors = self._check(lambda r: r["sections"][0]["sentences"].extend([filler] * 20))
        self.assertTrue(any("Texte trop long" in e for e in errors))

    def test_verdict_color_must_appear(self):
        def strip_color(report):
            for sec in report["sections"]:
                for s in sec["sentences"]:
                    s["text"] = s["text"].replace("jaune", "orange")
        self.assertTrue(any("couleur" in e for e in self._check(strip_color)))


class LlmPathTests(unittest.TestCase):
    def setUp(self):
        self.v, self.p, self.a = _verdict("mateo", "QQQ", 2000), PROFILES["mateo"], ASSETS["QQQ"]
        self.sheet = facts.build_fact_sheet(self.v, self.p, self.a, "intermediaire")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _build(self, client, **kw):
        return build_report(self.v, self.p, self.a, mode="llm", client=client, cache_dir=self.tmp.name, **kw)

    def test_valid_answer_is_used_and_cached(self):
        client = FakeClient(_llm_json_from_template(self.sheet))
        res = self._build(client)
        self.assertEqual((res["meta"]["mode"], res["meta"]["attempts"], res["meta"]["cache_hit"]), ("llm", 1, False))
        self.assertEqual(len(client.calls), 1)
        sent = json.dumps(client.calls[0], ensure_ascii=False)
        self.assertNotIn("temperature", sent)                      # paramètre déprécié sur ces modèles
        self.assertNotIn(self.p["user_id"], sent)                  # aucun identifiant envoyé au modèle
        again = self._build(FakeClient(RuntimeError("ne doit pas être appelé")))
        self.assertTrue(again["meta"]["cache_hit"])
        self.assertEqual(again["report"], res["report"])

    def test_invalid_then_valid_answer_uses_the_retry(self):
        bad = _llm_json_from_template(self.sheet, lambda d: d["sections"][0]["sentences"].append(
            {"text": "Achetez cette action, elle vaut 999 points.", "facts": ["F1"]}))
        client = FakeClient(bad, _llm_json_from_template(self.sheet))
        res = self._build(client)
        self.assertEqual(res["meta"]["attempts"], 2)
        self.assertIn("refusée", json.dumps(client.calls[1], ensure_ascii=False))     # les erreurs sont renvoyées au modèle

    def test_two_failures_fall_back_to_the_fixed_text(self):
        bad = _llm_json_from_template(self.sheet, lambda d: d["sections"][0]["sentences"].append(
            {"text": "Vendez tout, 12345 %.", "facts": ["F1"]}))
        res = self._build(FakeClient(bad))
        self.assertEqual(res["meta"]["mode"], "template")
        self.assertTrue(res["meta"]["fallback_reason"])
        self.assertEqual(verify.verify_report(res["report"], res["sheet"]), [])
        self.assertIn("repli", " ".join(t["detail"] for t in res["trace"]))

    def test_network_error_and_garbage_fall_back(self):
        for client in (FakeClient(ConnectionError("réseau")), FakeClient("pas du json du tout")):
            res = self._build(client)
            self.assertEqual(res["meta"]["mode"], "template")

    def test_template_mode_never_calls_a_client(self):
        client = FakeClient("{}")
        build_report(self.v, self.p, self.a, mode="template", client=client)
        self.assertEqual(client.calls, [])

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            build_report(self.v, self.p, self.a, mode="magie")

    def test_cache_key_changes_with_content(self):
        other = facts.build_fact_sheet(_verdict("robert", "TSLA"), PROFILES["robert"], ASSETS["TSLA"], "intermediaire")
        self.assertNotEqual(llm_text.cache_key(self.sheet, "m"), llm_text.cache_key(other, "m"))
        self.assertNotEqual(llm_text.cache_key(self.sheet, "m1"), llm_text.cache_key(self.sheet, "m2"))


class ChartTests(unittest.TestCase):
    def test_charts_are_deterministic_and_accessible(self):
        v, p, a = _verdict("mateo", "QQQ", 2000), PROFILES["mateo"], ASSETS["QQQ"]
        builders = {
            "gap": lambda: charts.gap_chart(v), "components": lambda: charts.components_chart(v),
            "profile": lambda: charts.profile_chart(p), "price": lambda: charts.price_chart(a),
            "universe": lambda: charts.universe_chart(v, UNIVERSE),
        }
        for name, build in builders.items():
            c1, c2 = build(), build()
            with self.subTest(chart=name):
                self.assertEqual(c1, c2)
                self.assertIn("<title", c1["svg"])
                self.assertIn("<desc", c1["svg"])
                self.assertIn('role="img"', c1["svg"])
                self.assertTrue(c1["table"]["rows"])
                self.assertNotIn("NaN", c1["svg"])
                self.assertNotIn("http://", c1["svg"].replace("http://www.w3.org", ""))

    def test_gap_chart_matches_the_verdict(self):
        v = _verdict("robert", "TSLA")
        c = charts.gap_chart(v)
        self.assertIn(f"risque {facts.fr(v['asset']['score'], 0)}", c["svg"])
        self.assertIn(f"tolérance : {facts.fr(v['user']['effective_tolerance'], 0)}", c["svg"])
        self.assertIn("Rouge", c["svg"])                          # zone nommée : pas de couleur seule

    def test_components_chart_flags_the_ones_over_tolerance(self):
        v = _verdict("robert", "TSLA")
        self.assertEqual(charts.components_chart(v)["svg"].count("▲ dépasse"), 4)
        v2 = _verdict("amira", "ZST.TO")
        self.assertEqual(charts.components_chart(v2)["svg"].count("▲ dépasse"), 0)

    def test_price_chart_marks_the_real_maximum_drawdown(self):
        c = charts.price_chart(ASSETS["TSLA"])
        mdd = next(d for d in _verdict("robert", "TSLA")["drivers"] if d["key"] == "drawdown")["raw_value"]
        self.assertIn(f"-{facts.fr(mdd, 1)} %", c["svg"])

    def test_universe_chart_has_every_asset(self):
        c = charts.universe_chart(_verdict("robert", "TSLA"), UNIVERSE)
        self.assertEqual(len(c["table"]["rows"]), len(UNIVERSE))
        self.assertEqual(c["svg"].count("<circle"), len(UNIVERSE))

    def test_svg_ids_are_stable_across_runs(self):
        a = charts.gap_chart(_verdict("robert", "TSLA"))["svg"]
        self.assertEqual(charts.hash_id("x"), charts.hash_id("x"))
        self.assertRegex(a, r'aria-labelledby="t\d+ d\d+"')


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.headings, self.ids = [], [], []
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.append((tag, dict(attrs)))
        if "id" in dict(attrs):
            self.ids.append(dict(attrs)["id"])


class HtmlTests(unittest.TestCase):
    def _page(self, persona, ticker, amount=None, **kw):
        return render_html.make_report_page(PROFILES[persona], ticker, planned_amount_cad=amount, **kw)

    def test_page_structure_and_accessibility(self):
        for persona, ticker, amount in CASES:
            html, info = self._page(persona, ticker, amount)
            parser = _Collect()
            parser.feed(html)
            with self.subTest(case=(persona, ticker)):
                self.assertTrue(html.startswith("<!doctype html>"))
                self.assertIn('<html lang="fr"', html)
                self.assertEqual(parser.tags.count("h1"), 1)
                self.assertEqual(parser.tags.count("main"), 1)
                self.assertEqual(parser.tags.count("script"), 0)
                self.assertEqual(len(parser.ids), len(set(parser.ids)))
                self.assertGreaterEqual(parser.tags.count("svg"), 5)
                self.assertNotRegex(html, r'(src|href)="https?://')
                self.assertNotIn("@import", html)
                self.assertNotIn("<figcaption", html)
                for tag, attrs in parser.attrs:
                    if tag == "img":
                        self.fail("aucune image externe attendue")
                for cite in re.findall(r'href="#(f\d+)"', html):
                    self.assertIn(cite, parser.ids)

    def test_page_numbers_match_the_verdict(self):
        html, info = self._page("robert", "TSLA")
        v = info["verdict"]
        self.assertIn(facts.fr(v["asset"]["score"], 0), html)
        self.assertIn(v["final_color"], html)
        for d in config.ASSET_DISCLAIMERS:
            self.assertIn(d.replace("'", "&#x27;"), html)

    def test_page_is_deterministic(self):
        self.assertEqual(self._page("mateo", "QQQ", 2000)[0], self._page("mateo", "QQQ", 2000)[0])

    def test_reduced_motion_and_dark_mode_are_handled(self):
        html, _ = self._page("mateo", "SPY")
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn("prefers-color-scheme:dark", html)
        self.assertIn("color-scheme", html)
        self.assertIn(":focus-visible", html)

    def test_html_is_escaped(self):
        p = copy.deepcopy(PROFILES["mateo"])
        p["user_id"] = "<script>alert(1)</script>"
        html, _ = render_html.make_report_page(p, "SPY")
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_write_report(self):
        html, _ = self._page("mateo", "SPY")
        with tempfile.TemporaryDirectory() as d:
            path = render_html.write_report(Path(d) / "sous" / "rapport.html", html)
            self.assertEqual(path.read_text(encoding="utf-8"), html)

    def test_llm_mode_with_fake_client_renders(self):
        sheet = facts.build_fact_sheet(_verdict("mateo", "QQQ", 2000), PROFILES["mateo"], ASSETS["QQQ"], "intermediaire")
        with tempfile.TemporaryDirectory() as d:
            html, info = self._page("mateo", "QQQ", 2000, mode="llm", client=FakeClient(_llm_json_from_template(sheet)),
                                    cache_dir=d)
        self.assertEqual(info["result"]["meta"]["mode"], "llm")
        self.assertIn(config.REPORT_MODEL_ID, html)


if __name__ == "__main__":
    unittest.main()
