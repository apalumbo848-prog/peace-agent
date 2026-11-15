"""Serveur local de démonstration (bibliothèque standard seulement, aucun framework).

    python -m agent_risque.app.server            # texte fixe pour le rapport
    python -m agent_risque.app.server --llm      # rapport reformulé par Bedrock (identifiants AWS requis)

Principes :
- écoute 127.0.0.1 seulement par défaut ; Host et Origin sont contrôlés (protège contre les pages tierces) ;
- déploiement public (AWS) : `--host 0.0.0.0 --allowed-hosts <domaine>` (ou `*`) ; l'Origin doit alors être celui de la page elle-même ;
- le calcul démarre à l'ouverture de la page d'une action, jamais avant ;
- les parties POST ne font que : enregistrer un achat SIMULÉ, effacer ce registre, poser une question.
"""

from __future__ import annotations

import argparse
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .. import asset_score, config, data_access
from ..agent import followup, tools
from ..report import render_html
from . import ledger, pages, service, situation_ledger

MAX_BODY = 4096
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}
_AMOUNT = re.compile(r"^\d{1,9}(?:[.,]\d{1,2})?$")


_UNIVERSE_CACHE: dict[str, float] = {}


def _universe_scores() -> dict[str, float]:
    """Score des 31 actifs à la date de référence : constant, donc calculé une fois par processus."""
    if not _UNIVERSE_CACHE:
        _UNIVERSE_CACHE.update({t: asset_score.score_asset(t, service.AS_OF).score for t in data_access.load_universe()})
    return _UNIVERSE_CACHE


class NewsGate:
    """Mémorise le résultat Actualité par action (5 min) et évite deux analyses simultanées de la même action.
    `prefetch` lance l'analyse pendant que la personne répond à la mise en situation (elle est de toute façon
    demandée par l'ouverture de cette page d'action)."""
    TTL_S = 300

    def __init__(self, provider):
        self.provider = provider
        self.memo: dict[str, tuple[float, dict | None]] = {}
        self.locks: dict[str, threading.Lock] = {}

    def get(self, ticker: str, refresh: bool = False) -> dict | None:
        lock = self.locks.setdefault(ticker, threading.Lock())
        asked_at = time.time()
        with lock:
            hit = self.memo.get(ticker)
            if hit and hit[0] >= asked_at:                      # une analyse est arrivée pendant l'attente : on la réutilise
                return hit[1]
            if hit and not refresh and time.time() - hit[0] < self.TTL_S:
                return hit[1]
            try:
                value = self.provider(ticker, refresh)
            except Exception:                                   # l'actualité ne doit jamais bloquer le verdict
                value = None
            self.memo[ticker] = (time.time(), value)
            return value

    def get_within(self, ticker: str, refresh: bool = False, timeout: float = 4.0) -> dict | None:
        """Comme `get`, mais n'attend que `timeout` secondes : la page ne reste pas bloquée sur l'analyse (l'analyse continue
        en arrière-plan et la page suivante la trouvera en mémoire). Si elle n'est pas finie : statut « en_cours »."""
        box: list = []
        done = threading.Event()

        def run():
            box.append(self.get(ticker, refresh))
            done.set()
        threading.Thread(target=run, daemon=True).start()
        if done.wait(timeout):
            return box[0]
        return {"status": "en_cours"}

    def prefetch(self, ticker: str) -> None:
        threading.Thread(target=self.get, args=(ticker,), daemon=True).start()


class BadRequest(ValueError):
    pass


def parse_amount(raw: str | None) -> float:
    """« 2000 », « 2 000 », « 2000,50 » -> float ; refuse tout le reste (négatif, lettres, vide, énorme)."""
    text = (raw or "").replace(" ", "").replace(" ", "").replace("\xa0", "")
    if not _AMOUNT.match(text):
        raise BadRequest("Montant invalide : écrivez un nombre positif, par exemple 2000 ou 2000,50.")
    value = float(text.replace(",", "."))
    if not 0 < value <= config.APP_MAX_AMOUNT_CAD:
        raise BadRequest(f"Le montant doit être entre 0 et {config.APP_MAX_AMOUNT_CAD:,.0f} $ CAD.".replace(",", " "))
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentRisque/1.0"
    report_mode = "template"                  # fixé au démarrage (--llm)
    question_counts: dict[tuple[str, str], int] = {}     # (profil, titre) -> questions libres posées
    ledger_dir = None                         # remplaçable dans les tests
    ask_situations = True                     # False : n'affiche pas la mise en situation (tests)
    news_gate: NewsGate | None = None         # None : actualité désactivée (tests, --no-news)
    fx_provider = None                        # callable(montant_cad) -> dict | None ; None : taux du jour désactivé

    def _news(self, ticker: str, refresh: bool = False) -> dict | None:
        return self.news_gate.get_within(ticker, refresh, config.NEWS_PAGE_WAIT_S) if self.news_gate else None

    def _fx(self, amount: float) -> dict | None:
        if self.fx_provider is None:
            return None
        try:
            return self.fx_provider(amount)
        except Exception:
            return None

    # ------------------------------------------------------------ utilitaires
    def log_message(self, fmt, *args):        # journal court, sans le contenu des requêtes
        pass

    def _send(self, html: str, status: int = 200, location: str | None = None) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    allowed_hosts: frozenset | None = None   # None : mode local ; sinon noms d'hôte publics acceptés (« * » = tous)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        if self.allowed_hosts is not None:
            return "*" in self.allowed_hosts or host.rsplit(":", 1)[0] in self.allowed_hosts or host in self.allowed_hosts
        return host in {f"{config.APP_HOST}:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        if self.allowed_hosts is not None:        # public : seule la page elle-même peut envoyer ses formulaires
            return origin.lower().split("://", 1)[-1] == (self.headers.get("Host") or "").lower()
        return origin.lower() in {f"http://{config.APP_HOST}:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}

    def _persona(self, params: dict) -> str:
        persona = (params.get("u") or [""])[0]
        if persona not in service.persona_keys():
            raise BadRequest("Profil inconnu.")
        return persona

    @staticmethod
    def _first(params: dict, key: str) -> str:
        return (params.get(key) or [""])[0]

    def _ticker(self, raw: str) -> str:
        ticker = unquote(raw)
        if data_access.get_asset(ticker) is None:
            raise BadRequest("Titre absent des données.")
        return ticker

    # ------------------------------------------------------------ routes GET
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            return self._send(pages.error_page("Hôte non autorisé."), HTTPStatus.FORBIDDEN)
        try:
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            if method == "POST":
                if not self._origin_ok():
                    return self._send(pages.error_page("Origine non autorisée."), HTTPStatus.FORBIDDEN)
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(pages.error_page("Requête trop grande."), HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                params = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            self._route(method, url.path, params)
        except BadRequest as exc:
            self._send(pages.error_page(str(exc)), HTTPStatus.BAD_REQUEST)
        except (ledger.LedgerError, asset_score.AssetScoreError) as exc:
            self._send(pages.error_page(str(exc)), HTTPStatus.UNPROCESSABLE_ENTITY)
        except Exception:                                       # jamais de trace Python dans la page
            self._send(pages.error_page("Erreur interne : la page n'a pas pu être calculée."), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _route(self, method: str, path: str, params: dict) -> None:
        if method == "GET" and path == "/":
            if not params.get("u"):
                return self._send(pages.persona_picker())
            persona = self._persona(params)
            profile = service.build_profile(persona, self.ledger_dir)
            return self._send(pages.home(persona, profile, config.APP_DEFAULT_AMOUNT_CAD))
        if method == "GET" and path == "/profil":
            persona = self._persona(params)
            profile = service.build_profile(persona, self.ledger_dir)
            purchases = ledger.load(service.user_id_of(persona), self.ledger_dir)
            return self._send(pages.profile_page(persona, profile, purchases, self._first(params, "note")))
        if method == "GET" and path.startswith("/asset/"):
            persona, ticker = self._persona(params), self._ticker(path[len("/asset/"):])
            if self.ask_situations and service.needs_situation(persona, ticker, self.ledger_dir):
                if not params.get("amount"):                      # d'abord le montant, ensuite la mise en situation
                    return self._send(pages.amount_step_page(persona, ticker, data_access.get_asset(ticker).name,
                                                             config.APP_DEFAULT_AMOUNT_CAD))
                # Première ouverture de cette action : la mise en situation s'affiche en pop-up AVANT le verdict.
                return self._situation_page(persona, ticker, params)
            return self._asset_page(persona, ticker, params)
        if method == "GET" and path.startswith("/situation/"):
            return self._situation_page(self._persona(params), self._ticker(path[len("/situation/"):]), params)
        if method == "POST" and path == "/situation":
            return self._situation_submit(params)
        if method == "POST" and path == "/achat":
            return self._purchase(params)
        if method == "POST" and path == "/question":
            return self._question(params)
        if method == "POST" and path == "/reinitialiser":
            persona = self._persona(params)
            ledger.reset(service.user_id_of(persona), self.ledger_dir)
            situation_ledger.reset(service.user_id_of(persona), self.ledger_dir)
            return self._send("", HTTPStatus.SEE_OTHER, f"/profil?u={persona}&note=Achats+et+mises+en+situation+effac%C3%A9s")
        self._send(pages.error_page("Page introuvable.", status_hint="404"), HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------ page d'une action
    def _asset_page(self, persona: str, ticker: str, params: dict, answer: dict | None = None, notice: str = "") -> None:
        try:
            amount = parse_amount(self._first(params, "amount") or pages.fmt_amount(config.APP_DEFAULT_AMOUNT_CAD))
        except BadRequest as exc:
            amount, notice = config.APP_DEFAULT_AMOUNT_CAD, str(exc)
        news = self._news(ticker, refresh=bool(self._first(params, "refresh")))
        ctx = service.open_asset_page(persona, ticker, amount, self.ledger_dir, news)    # L'AGENT DÉMARRE ICI
        result = service.report_for(ctx, mode=self.report_mode)
        if answer is None:
            answer = self._preset_answer(ctx, result, self._first(params, "q"))
        used = self.question_counts.get((persona, ticker), 0)
        fx = self._fx(amount)
        extra = (pages.news_block(news if self.news_gate else None, persona, ticker, amount) +
                 pages.questions_block(persona, ticker, amount, answer,
                                       max(0, config.FOLLOWUP_MAX_QUESTIONS_PER_PAGE - used)))
        top = pages.purchase_block(persona, ticker, amount, notice, fx)
        info = ctx.asset.news
        if info and info.get("status") == "ok" and info.get("adjustment"):
            top = (f'<p class="hint news-note">L’actualité récente a relevé le risque de cette action de '
                   f'{pages._fr1(info["adjustment"])} point(s) (événements confirmés par 2 sources ou nombreux articles défavorables). '
                   'Détails dans « En savoir plus ».</p>') + top
        color = ctx.verdict["final_color"]
        lead = {"vert": "Le risque de cette action est en accord avec votre tolérance calculée.",
                "jaune": "Le risque de cette action dépasse un peu votre tolérance calculée.",
                "rouge": "Le risque de cette action est bien au-dessus de votre tolérance calculée."}[ctx.verdict["risk_color"]]
        if color != ctx.verdict["risk_color"]:                  # une contrainte déclarée (exclusion, concentration, horizon) relève la couleur
            lead += " Une de vos contraintes déclarées relève aussi le verdict."
        open_more = bool(answer) or bool(self._first(params, "q")) or bool(self._first(params, "more"))
        universe = _universe_scores()
        html = render_html.render_report(result, ctx.verdict, ctx.profile, ctx.asset, universe,
                                         nav_html=pages.nav(persona), before_trace_html=extra, extra_css=pages.EXTRA_CSS,
                                         top_html=top, collapse=True, open_more=open_more, simple_lead=lead,
                                         bottom_html=pages.fx_sources(fx))
        self._send(html)

    @staticmethod
    def _preset_answer(ctx: service.Context, result: dict, kind: str) -> dict | None:
        if kind not in ("why", "profile", "scenario"):
            return None
        fctx = tools.FollowupContext(result["sheet"], ctx.verdict, ctx.profile, ctx.asset, ctx.amount_cad)
        if kind == "why":
            sentences = tools.preset_why_color(fctx)
        elif kind == "profile":
            sentences = tools.preset_profile(fctx)
        else:
            sentences = tools.preset_scenario(fctx, max(1.0, round(ctx.amount_cad / 2)))
        errors = followup.verify_answer(sentences, fctx)
        if errors:                                              # ne devrait jamais arriver : on le dit plutôt que de l'afficher
            return {"kind": "echec", "sentences": [{"text": config.FOLLOWUP_FAILURE_FR, "facts": []}],
                    "tool_log": [], "extra_facts": [], "error": "; ".join(errors[:2])}
        return {"kind": "preset", "sentences": sentences, "tool_log": fctx.tool_log, "extra_facts": fctx.extra_facts, "error": None}

    # ------------------------------------------------------------ mise en situation
    def _situation_page(self, persona: str, ticker: str, params: dict, error: str = "") -> None:
        try:
            amount = parse_amount(self._first(params, "amount") or pages.fmt_amount(config.APP_DEFAULT_AMOUNT_CAD))
        except BadRequest:
            amount = config.APP_DEFAULT_AMOUNT_CAD
        asset = data_access.get_asset(ticker)
        if self.news_gate:
            self.news_gate.prefetch(ticker)          # l'analyse d'actualité avance pendant que la personne répond
        self._send(pages.situation_page(persona, ticker, asset.name, amount, error))

    def _situation_submit(self, params: dict) -> None:
        persona, ticker = self._persona(params), self._ticker(self._first(params, "ticker"))
        user_id = service.user_id_of(persona)
        amount_text = self._first(params, "amount") or pages.fmt_amount(config.APP_DEFAULT_AMOUNT_CAD)
        back = f"/asset/{quote(ticker, safe='')}?u={persona}&amount={quote(amount_text, safe='')}"
        if situation_ledger.answered_tickers(user_id, self.ledger_dir) >= {ticker}:
            return self._send("", HTTPStatus.SEE_OTHER, back)                     # déjà traité : pas de doublon
        if self._first(params, "action") == "skip":
            situation_ledger.record(user_id, {"ticker": ticker, "skipped": True}, self.ledger_dir)
            return self._send("", HTTPStatus.SEE_OTHER, back)
        try:
            levels, trades = len(config.SITUATION_LADDER_LEVELS), len(config.SITUATION_TRADEOFFS)
            ladder = [self._yes_no(params, f"ladder_{i}") for i in range(levels)]
            tradeoff = [self._yes_no(params, f"tradeoff_{i}") for i in range(trades)]
            reaction = int(self._first(params, "reaction"))
            situation_ledger.record(user_id, {"ticker": ticker, "ladder": ladder, "reaction": reaction,
                                              "tradeoff": tradeoff}, self.ledger_dir)
        except ValueError:
            return self._situation_page(persona, ticker, params, "Répondez à chaque question, ou choisissez « Passer cette étape ».")
        self._send("", HTTPStatus.SEE_OTHER, back)

    @staticmethod
    def _yes_no(params: dict, key: str) -> bool:
        value = (params.get(key) or [""])[0]
        if value not in ("oui", "non"):
            raise ValueError(key)
        return value == "oui"

    # ------------------------------------------------------------ POST
    def _purchase(self, params: dict) -> None:
        persona, ticker = self._persona(params), self._ticker(self._first(params, "ticker"))
        amount = parse_amount(self._first(params, "amount"))
        ctx = service.open_asset_page(persona, ticker, amount, self.ledger_dir, self._news(ticker))   # verdict recalculé côté serveur
        result = service.simulate_purchase(persona, ticker, amount, self.ledger_dir)
        self._send(pages.purchase_result(persona, ticker, result))

    def _question(self, params: dict) -> None:
        persona, ticker = self._persona(params), self._ticker(self._first(params, "ticker"))
        amount = parse_amount(self._first(params, "amount"))
        question = self._first(params, "question")
        key = (persona, ticker)
        if self.question_counts.get(key, 0) >= config.FOLLOWUP_MAX_QUESTIONS_PER_PAGE:
            answer = {"kind": "invalide", "sentences": [], "tool_log": [], "extra_facts": [],
                      "error": "Limite de questions libres atteinte pour cette action."}
        else:
            ctx = service.open_asset_page(persona, ticker, amount, self.ledger_dir, self._news(ticker))
            result = service.report_for(ctx, mode="template")
            fctx = tools.FollowupContext(result["sheet"], ctx.verdict, ctx.profile, ctx.asset, ctx.amount_cad)
            answer = followup.ask_free(fctx, question)
            if answer["kind"] in ("agent", "echec"):            # seules les questions qui appellent le modèle comptent
                self.question_counts[key] = self.question_counts.get(key, 0) + 1
        self._asset_page(persona, ticker, {"amount": [pages.fmt_amount(amount)]}, answer=answer)


def make_server(port: int | None = None, report_mode: str = "template", ledger_dir=None,
                ask_situations: bool = True, news_provider=None, fx_provider=None,
                host: str | None = None, allowed_hosts=None) -> ThreadingHTTPServer:
    """news_provider(ticker, refresh) -> dict et fx_provider(montant) -> dict : None les désactive (tests)."""
    handler = type("ConfiguredHandler", (Handler,), {
        "report_mode": report_mode, "ledger_dir": ledger_dir, "question_counts": {}, "ask_situations": ask_situations,
        "news_gate": NewsGate(news_provider) if news_provider else None, "fx_provider": staticmethod(fx_provider) if fx_provider else None,
        "allowed_hosts": frozenset(h.strip().lower() for h in allowed_hosts) if allowed_hosts else None})
    return ThreadingHTTPServer((host or config.APP_HOST, config.APP_PORT if port is None else port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Page de démonstration de Peace, l'agent de risque (simulation).")
    parser.add_argument("--llm", action="store_true", help="reformule le rapport avec Amazon Bedrock")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT") or config.APP_PORT))
    parser.add_argument("--host", default=os.environ.get("PEACE_HOST") or config.APP_HOST,
                        help="adresse d'écoute ; 0.0.0.0 pour un déploiement public (AWS)")
    parser.add_argument("--allowed-hosts", default=os.environ.get("PEACE_ALLOWED_HOSTS", ""),
                        help="noms d'hôte publics acceptés, séparés par des virgules (« * » : tous) ; vide : mode local")
    parser.add_argument("--no-news", action="store_true", help="désactive l'agent Actualité et le taux du jour")
    args = parser.parse_args()
    allowed = [h for h in args.allowed_hosts.split(",") if h.strip()]
    net = {"host": args.host, "allowed_hosts": allowed}
    if args.no_news:
        server = make_server(args.port, "llm" if args.llm else "template", **net)
    else:
        from .. import fx_live
        from ..news import service as news_service
        server = make_server(args.port, "llm" if args.llm else "template",
                             news_provider=lambda t, refresh: news_service.get_news(t, refresh=refresh),
                             fx_provider=lambda amount: fx_live.summary(amount, service.AS_OF), **net)
    print(f"Ouvrez http://{args.host}:{server.server_port}/  (Ctrl+C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
