"""Actualité (agent filtreur) et taux du jour : tout est testé HORS LIGNE (faux flux, faux agent, faux taux)."""

import http.client
import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path

from agent_risque import asset_score, combine, comparison, config, fx_live
from agent_risque.app import server as app_server
from agent_risque.fixtures import personas
from agent_risque.news import adjust, feeds, impact
from agent_risque.news import agent as news_agent
from agent_risque.news import service as news_service

AS_OF = personas.AS_OF
QUOTE = "Tesla recalls 200,000 vehicles after a battery fire investigation opened by regulators"


def rss(items: list[tuple[str, str, str]]) -> bytes:
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate>"
                   f"<description>{d}</description></item>" for t, l, d in items)
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{body}</channel></rss>".encode()


def make_fetcher(calls: list):
    def fetch(url: str) -> bytes:
        calls.append(url)
        if "theguardian" in url:
            return rss([("Tesla recall widens", "https://g.example/a", QUOTE + ".")])
        if "bbci" in url:
            return rss([("Tesla battery probe", "https://b.example/a", QUOTE + ", officials said.")])
        if "foxbusiness" in url:
            return rss([("Markets calm", "https://f.example/a", "Nothing about any company.")])
        if "example" in url:
            return b"<html><body><p>" + (QUOTE + ". " * 12).encode() + b"</p></body></html>"
        raise OSError("hors ligne")
    return fetch


def fake_agent(events_for):
    """Fabrique d'agent factice : lit tous les articles listés, puis répond avec les événements voulus."""
    def factory(ctx):
        def agent(prompt: str):
            ids = [line.split(" | ")[0] for line in ctx.listing().splitlines() if " | " in line]
            for i in ids:
                ctx.read(i)
            return json.dumps({"events": events_for(ids)})
        return agent
    return factory


def two_source_events(ids, severity=(2, 2)):
    return [{"article_id": ids[0], "type": "enquete_ou_poursuite", "severity": severity[0], "quote": QUOTE,
             "summary": "Rappel de véhicules après une enquête."},
            {"article_id": ids[1], "type": "enquete_ou_poursuite", "severity": severity[1], "quote": QUOTE,
             "summary": "Enquête sur des batteries."}]


class FeedTests(unittest.TestCase):
    def test_parse_and_refuse_entities(self):
        arts = feeds.parse_feed(rss([("Titre <b>x</b>", "https://a.example/1", "<p>Résumé</p>")]),
                                {"id": "s", "name": "S", "orientation": "neutre"})
        self.assertEqual(arts[0].title, "Titre x")
        self.assertEqual(arts[0].published, "2026-11-13")
        bomb = b"<?xml version='1.0'?><!DOCTYPE r [<!ENTITY a 'x'>]><rss><channel><item><title>&a;</title></item></channel></rss>"
        with self.assertRaises(ValueError):
            feeds.parse_feed(bomb, {"id": "s", "name": "S", "orientation": "neutre"})

    def test_non_http_links_are_dropped(self):
        arts = feeds.parse_feed(rss([("T", "javascript:alert(1)", "d"), ("U", "https://ok.example/1", "d")]),
                                {"id": "s", "name": "S", "orientation": "neutre"})
        self.assertEqual([a.title for a in arts], ["U"])

    def test_relevance_and_diversity(self):
        a = feeds.Article("g-0", "guardian", "G", "gauche", "Tesla recall", "https://x.example", "2026-11-12", "")
        b = feeds.Article("f-0", "foxbusiness", "F", "droite", "Weather", "https://y.example", "2026-11-13", "rain")
        self.assertTrue(feeds.is_relevant(a, "TSLA", "Tesla"))
        self.assertFalse(feeds.is_relevant(b, "TSLA", "Tesla"))
        self.assertEqual([x.id for x in feeds.select([a, b], "TSLA", "Tesla")], ["g-0"])

    def test_extract_text_skips_scripts_and_short_paragraphs(self):
        html = b"<nav><p>menu menu menu menu menu menu menu menu menu menu</p></nav><script>var a=1</script><p>court</p><p>" + b"x" * 60 + b"</p>"
        self.assertEqual(feeds.extract_text(html), "x" * 60)


class VerificationTests(unittest.TestCase):
    def ctx(self):
        a = feeds.Article("g-0", "guardian", "The Guardian", "gauche", "Tesla recall", "https://g.example/a", "2026-11-13",
                          QUOTE + ".")
        c = news_agent.NewsContext("TSLA", "Tesla", "Consumer Discretionary", {a.id: a})
        c.read("g-0")
        return c

    def event(self, **kw):
        base = {"article_id": "g-0", "type": "enquete_ou_poursuite", "severity": 2, "quote": QUOTE, "summary": "x"}
        return {**base, **kw}

    def test_good_event_is_accepted(self):
        ok, rej = news_agent.verify_events([self.event()], self.ctx())
        self.assertEqual((len(ok), len(rej)), (1, 0))

    def test_invented_quote_unknown_type_bad_severity_unread_article(self):
        ctx = self.ctx()
        bad = [self.event(quote="Tesla will go bankrupt next week according to insiders, a very long invented sentence"),
               self.event(type="rumeur"), self.event(severity=9), self.event(severity=True),
               self.event(article_id="zzz"), self.event(quote="trop court")]
        ok, rej = news_agent.verify_events(bad, ctx)
        self.assertEqual(ok, [])
        self.assertEqual(len(rej), len(bad))
        fresh = news_agent.NewsContext("TSLA", "Tesla", "x", dict(ctx.articles))      # article jamais ouvert
        self.assertEqual(len(news_agent.verify_events([self.event()], fresh)[0]), 0)


class ImpactTests(unittest.TestCase):
    def ev(self, source, sev, etype="enquete_ou_poursuite"):
        return {"type": etype, "severity": sev, "source_id": source, "source_name": source, "orientation": "neutre"}

    def test_single_source_has_no_effect(self):
        r = impact.assess([self.ev("a", 3)])
        self.assertEqual((r["adjustment"], r["n_corroborated"]), (0.0, 0))

    def test_two_sources_use_lowest_severity(self):
        r = impact.assess([self.ev("a", 3), self.ev("b", 2)])
        self.assertEqual(r["adjustment"], config.NEWS_SEVERITY_POINTS[2])
        self.assertEqual(r["extra_margin"], 0.0)

    def test_cap_and_divergence(self):
        evs = [self.ev(s, 3, t) for t in config.NEWS_EVENT_TYPES for s in ("a", "b")]
        self.assertEqual(impact.assess(evs)["adjustment"], config.NEWS_MAX_POINTS)
        self.assertTrue(impact.assess(evs)["capped"])
        r = impact.assess([self.ev("a", 3), self.ev("b", 1)])
        self.assertEqual(r["extra_margin"], config.NEWS_DIVERGENCE_MARGIN)
        self.assertEqual(r["adjustment"], config.NEWS_SEVERITY_POINTS[1])

    def test_no_events_means_no_change(self):
        self.assertEqual(impact.assess([])["adjustment"], 0.0)


class AdjustTests(unittest.TestCase):
    def test_score_only_goes_up_and_is_capped_and_unavailable_is_neutral(self):
        base = asset_score.score_asset("TSLA", AS_OF)
        up = adjust.apply_news(base, {"status": "ok", "adjustment": 3.5, "extra_margin": 0.0})
        self.assertAlmostEqual(up.score, min(100.0, base.score + 3.5))
        self.assertEqual(adjust.apply_news(base, {"status": "indisponible"}).score, base.score)
        self.assertEqual(adjust.apply_news(base, None), base)
        btc = asset_score.score_asset("ETH-USD", AS_OF)
        self.assertLessEqual(adjust.apply_news(btc, {"status": "ok", "adjustment": 5.0, "extra_margin": 0.0}).score, 100.0)

    def test_divergence_widens_margin_and_lowers_tolerance(self):
        profile = combine.compute_user_profile(**personas.all_personas()["mateo"])
        base = asset_score.score_asset("SPY", AS_OF)
        plain = comparison.compare(profile, adjust.apply_news(base, {"status": "ok", "adjustment": 0.0, "extra_margin": 0.0}))
        wide = comparison.compare(profile, adjust.apply_news(base, {"status": "ok", "adjustment": 0.0, "extra_margin": 3.0}))
        self.assertAlmostEqual(plain["user"]["effective_tolerance"] - wide["user"]["effective_tolerance"], 3.0, places=3)
        self.assertEqual(wide["news"]["extra_margin"], 3.0)


class ServiceTests(unittest.TestCase):
    def run_service(self, directory, events_for=two_source_events, **kw):
        calls: list = []
        result = news_service.get_news("TSLA", Path(directory), fetcher=make_fetcher(calls),
                                       agent_factory=fake_agent(events_for), today=date(2026, 11, 13), **kw)
        return result, calls

    def test_end_to_end_and_snapshot_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            result, calls = self.run_service(d)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["adjustment"], config.NEWS_SEVERITY_POINTS[2])
            self.assertEqual({e["orientation"] for e in result["events"]}, {"gauche", "neutre"})
            self.assertTrue(calls)
            again, calls2 = self.run_service(d)
            self.assertEqual(again, result)
            self.assertEqual(calls2, [])                                      # aucun appel réseau : instantané relu
            _, calls3 = self.run_service(d, refresh=True)
            self.assertTrue(calls3)                                           # « actualiser » relance la chaîne

    def test_fabricated_events_are_rejected_and_do_not_move_the_score(self):
        def liar(ids):
            return [{"article_id": ids[0], "type": "enquete_ou_poursuite", "severity": 3,
                     "quote": "Tesla is under criminal investigation for fraud, a sentence never written", "summary": "x"}] * 2
        with tempfile.TemporaryDirectory() as d:
            result, _ = self.run_service(d, liar)
            self.assertEqual((result["status"], result["adjustment"], len(result["events"])), ("ok", 0.0, 0))
            self.assertEqual(len(result["rejected"]), 2)

    def test_agent_failure_is_reported_not_raised(self):
        def broken(ctx):
            raise RuntimeError("pas d'identifiants")
        with tempfile.TemporaryDirectory() as d:
            result = news_service.get_news("TSLA", Path(d), fetcher=make_fetcher([]), agent_factory=broken,
                                           today=date(2026, 11, 13))
            self.assertEqual(result["status"], "indisponible")
            self.assertEqual(result["adjustment"], 0.0)

    def test_all_sources_down(self):
        def down(url):
            raise OSError("hors ligne")
        with tempfile.TemporaryDirectory() as d:
            result = news_service.get_news("SPY", Path(d), fetcher=down, agent_factory=fake_agent(lambda ids: []),
                                           today=date(2026, 11, 13))
            self.assertEqual(result["status"], "indisponible")

    def test_no_relevant_article(self):
        with tempfile.TemporaryDirectory() as d:
            result = news_service.get_news("PG", Path(d), fetcher=make_fetcher([]), agent_factory=fake_agent(lambda ids: []),
                                           today=date(2026, 11, 13))
            self.assertEqual(result["status"], "aucune")


class FxTests(unittest.TestCase):
    def test_summary(self):
        s = fx_live.summary(1400.0, AS_OF, fetcher=lambda: {"rate": 1.4, "date": "2026-11-13"})
        self.assertAlmostEqual(s["amount_usd"], 1000.0)
        self.assertIsNotNone(s["change_pct"])

    def test_failure_returns_none(self):
        def down():
            raise OSError
        self.assertIsNone(fx_live.summary(100.0, AS_OF, fetcher=down))


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        news = {"status": "ok", "adjustment": 2.0, "extra_margin": 0.0, "capped": False, "n_events": 2, "n_corroborated": 1,
                "groups": [{"type": "enquete_ou_poursuite", "label": "x", "corroborated": True, "n_sources": 2,
                            "orientations": ["gauche", "neutre"], "severity": 2, "points": 2.0, "diverges": False}],
                "events": [{"article_id": "g-0", "source_id": "guardian", "source_name": "The Guardian", "orientation": "gauche",
                            "title": "<script>alert(1)</script>", "link": "https://g.example/a", "published": "2026-11-13",
                            "type": "enquete_ou_poursuite", "severity": 2, "quote": "<b>citation</b>", "summary": "Résumé."}],
                "rejected": [], "read": ["g-0"], "considered": [{}], "sources": {"guardian": "ok"},
                "retrieved_at": "2026-11-13 10:00 UTC", "error": None}
        fx = {"rate": 1.4257, "date": "2026-11-13", "source": "Banque du Canada (API Valet)", "reference_rate": 1.4255,
              "reference_date": "2026-11-12", "change_pct": 0.01, "amount_usd": 1402.82}
        cls.server = app_server.make_server(0, "template", Path(cls.dir), ask_situations=False,
                                            news_provider=lambda t, r: news, fx_provider=lambda a: fx)
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        r = conn.getresponse()
        return r.status, r.read().decode()

    def test_news_panel_and_note_and_escaping(self):
        status, html = self.get("/asset/TSLA?u=mateo&amount=2000")
        self.assertEqual(status, 200)
        self.assertIn("Actualité récente", html)
        self.assertIn("a relevé le risque de cette action", html)
        self.assertIn("1 402,82 $ US", html)                                   # conversion en haut, près du montant
        self.assertLess(html.index("1 402,82 $ US"), html.index('id="en-savoir-plus"'))
        self.assertGreater(html.index("Banque du Canada"), html.index('id="trace"'))   # source en bas, dans « + Sources »
        self.assertNotIn("Taux de change du jour", html)
        self.assertNotIn("<script>alert(1)</script>", html)                   # texte externe échappé
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("confirmé par 2 sources", html)


class VolumeRuleTests(unittest.TestCase):
    @staticmethod
    def ev(i, etype, source):
        return {"type": etype, "severity": 2, "source_id": source, "source_name": source, "orientation": "neutre", "link": f"http://x/{i}"}

    def test_many_unconfirmed_negative_articles_raise_the_score(self):
        types = list(config.NEWS_EVENT_TYPES)
        few = impact.assess([self.ev(i, types[i], f"s{i}") for i in range(2)])
        three = impact.assess([self.ev(i, types[i], f"s{i}") for i in range(3)])
        five = impact.assess([self.ev(i, types[i], f"s{i}") for i in range(5)])
        self.assertEqual(few["adjustment"], 0.0)
        self.assertEqual(three["adjustment"], 1.0)
        self.assertEqual(five["adjustment"], 2.0)
        self.assertEqual(three["volume"]["n_articles"], 3)

    def test_volume_never_exceeds_the_cap_and_does_not_recount_confirmed_events(self):
        t = list(config.NEWS_EVENT_TYPES)
        events = [self.ev(0, t[0], "a"), self.ev(1, t[0], "b")]                 # confirmé par 2 sources
        out = impact.assess(events)
        self.assertEqual(out["volume"]["n_articles"], 0)                        # déjà compté par la confirmation
        many = [self.ev(i, t[i % len(t)], f"s{i % 2}") for i in range(12)]
        self.assertLessEqual(impact.assess(many)["adjustment"], config.NEWS_MAX_POINTS)


class NewsGateWaitTests(unittest.TestCase):
    def test_slow_analysis_does_not_block_the_page_and_is_found_afterwards(self):
        import time
        release = threading.Event()

        def slow(ticker, refresh):
            release.wait(5)
            return {"status": "aucune"}
        gate = app_server.NewsGate(slow)
        t0 = time.time()
        self.assertEqual(gate.get_within("SPY", timeout=0.2), {"status": "en_cours"})
        self.assertLess(time.time() - t0, 2)
        release.set()
        self.assertEqual(gate.get_within("SPY", timeout=3), {"status": "aucune"})   # trouvée une fois terminée

    def test_pending_status_is_stated_and_changes_no_score(self):
        asset = asset_score.score_asset("SPY", personas.AS_OF)
        out = adjust.apply_news(asset, {"status": "en_cours"})
        self.assertEqual(out.score, asset.score)
        self.assertTrue(any("en cours d'analyse" in w for w in out.warnings))


if __name__ == "__main__":
    unittest.main()
