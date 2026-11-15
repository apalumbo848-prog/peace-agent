"""Gabarits HTML de la page de démonstration (HTML pur, sans JavaScript).

Chaque fonction retourne une chaîne ; tout texte variable passe par `escape`. Le style vient de
`report.render_html.CSS` (même charte que le rapport) plus quelques règles de formulaire.
"""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from .. import config, situations
from ..report import render_html
from . import service

EXTRA_CSS = """
.nav{border-bottom:1px solid var(--line);background:var(--surface)}
.nav .wrap{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;padding-block:12px;font-size:15px}
.nav a{color:var(--ink);padding:6px 2px}.nav b{margin-right:auto}
.sim{margin:0;padding:10px 0;font-size:14px;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:20px 0 0;padding:0;list-style:none}
.card{display:block;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px;color:var(--ink);
text-decoration:none;transition:border-color .2s ease,transform .2s ease}
.card:hover{border-color:var(--muted);transform:translateY(-2px)}.card b{display:block;font-size:18px;margin-bottom:4px}
.card span{color:var(--muted);font-size:14px}
form.box{margin-top:14px;display:grid;gap:12px;max-width:520px}
label{display:grid;gap:4px;font-weight:600;font-size:15px}
input[type=text],input[type=number],textarea,select{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--muted);
border-radius:8px;padding:10px 12px;width:100%}
label.check{display:flex;gap:10px;align-items:flex-start;font-weight:400}
label.check input{margin-top:5px;inline-size:18px;block-size:18px}
.btn{font:inherit;font-weight:700;color:var(--on-accent);background:var(--accent);border:2px solid var(--accent);border-radius:999px;
padding:10px 22px;cursor:pointer;justify-self:start;text-decoration:none;display:inline-block;
transition:background-color .15s ease,transform .15s ease}
.btn:hover{background:transparent;color:var(--accent)}.btn:active{transform:scale(.98)}
.btn.ghost{background:transparent;color:var(--accent)}.btn.ghost:hover{background:var(--accent);color:var(--on-accent)}
details.more>summary{list-style:none;cursor:pointer;display:inline-block;margin:8px 0 16px;padding:10px 20px;border:2px solid var(--accent);
border-radius:999px;font-weight:700;color:var(--accent);background:transparent;transition:background-color .15s ease,color .15s ease}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary{text-decoration:none}
.events{list-style:none;padding:0;margin:12px 0;display:grid;gap:12px}
.events li{border:1px solid var(--line);border-radius:12px;padding:12px 16px;background:var(--surface)}
.events p{margin:0 0 6px}.events a{overflow-wrap:anywhere}
blockquote{margin:8px 0;padding:6px 14px;border-left:3px solid var(--accent);color:var(--ink);overflow-wrap:anywhere}
details.more>summary:hover{background:var(--accent);color:var(--on-accent)}
details.more>summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
details.more[open]>summary{margin-bottom:8px}
.fx{margin:6px 0 0;color:var(--muted)}.fx b{color:var(--ink)}
details.src{margin-top:24px;font-size:13px;color:var(--muted)}details.src summary{display:inline-block;padding:2px 0}
details.src summary::before{content:"+ "}details.src[open] summary::before{content:"− "}details.src p{margin:6px 0 0;max-width:70ch}
.buy .row{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px}
.row{display:flex;flex-wrap:wrap;gap:10px}
.banner{border:2px solid var(--ink);border-radius:var(--radius);padding:12px 16px;background:var(--surface);margin:16px 0}
.banner.err{border-color:var(--no)}.banner.warn{border-color:var(--warn)}
.answer{margin-top:16px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px}
.answer h3{margin-top:0}.tag{font-size:13px;color:var(--muted)}
.hint{font-size:14px;color:var(--muted);margin:6px 0 0}
.backdrop{position:fixed;inset:0;z-index:20;display:grid;place-items:center;padding:16px;background:rgba(8,10,14,.72);
overflow:auto;overscroll-behavior:contain;animation:fade .2s ease both}
.modal{background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;width:100%;max-width:640px;
max-height:calc(100dvh - 32px);overflow:auto;overscroll-behavior:contain;padding:clamp(16px,3vw,28px);box-shadow:0 20px 60px rgba(0,0,0,.45)}
.modal h2{font-size:22px;margin:0 0 6px}.modal h3{font-size:16px;margin:20px 0 4px}.modal p{max-width:none}
.qrow{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px 16px;padding:10px 0;border-bottom:1px solid var(--line)}
.qrow>span:first-child{flex:1 1 260px}.qopts{display:flex;gap:8px}
.pill{display:inline-flex;cursor:pointer}.pill input{position:absolute;opacity:0;inline-size:1px;block-size:1px}
.pill span{border:1px solid var(--muted);border-radius:999px;padding:6px 16px;font-size:15px;transition:background-color .15s ease,color .15s ease}
.pill:hover span{border-color:var(--accent)}
.pill input:checked+span{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:600}
.pill input:focus-visible+span{outline:3px solid var(--accent);outline-offset:2px}
.mfoot{position:sticky;bottom:-1px;background:var(--surface);padding-top:14px;margin-top:14px}
@keyframes fade{from{opacity:0}to{opacity:1}}
fieldset.q{border:1px solid var(--line);border-radius:var(--radius);padding:12px 16px;margin:0 0 12px}
fieldset.q legend{font-weight:600;padding:0 6px}
form.wide{max-width:680px}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:12px 0 0}dl.kv dt{color:var(--muted)}dl.kv dd{margin:0}
@media (max-width:480px){dl.kv{grid-template-columns:1fr}}
"""


def fmt_amount(amount: float) -> str:
    """Montant pour un champ de formulaire : jamais de notation scientifique (5e+06)."""
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def _q(**params) -> str:
    return "&amp;".join(f"{k}={escape(quote(str(v), safe=''))}" for k, v in params.items())


def nav(persona: str | None) -> str:
    if not persona:
        return '<nav class="nav" aria-label="Navigation"><div class="wrap"><b>Peace · simulation</b></div></nav>'
    return ('<nav class="nav" aria-label="Navigation"><div class="wrap"><b>Peace · simulation</b>'
            f'<a href="/?{_q(u=persona)}">Actions</a><a href="/profil?{_q(u=persona)}">Mon profil</a>'
            '<a href="/">Changer de profil</a></div></nav>')


def shell(title: str, body: str, persona: str | None = None, description: str = "Simulation d'un agent explicable de risque d'investissement.") -> str:
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f7f7f4" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#101216" media="(prefers-color-scheme: dark)">
<style>{render_html.CSS}{EXTRA_CSS}</style>
</head>
<body>
<a class="skip" href="#contenu">Passer au contenu</a>
{nav(persona)}
<main id="contenu" class="wrap">
{body}
</main>
<footer><div class="wrap"><p>Simulation uniquement : aucune transaction réelle et aucun conseil financier personnalisé. Les profils sont fictifs.</p></div></footer>
</body>
</html>
"""


def persona_picker() -> str:
    cards = "".join(
        f'<li><a class="card" href="/?{_q(u=k)}"><b>{escape(service.PERSONA_LABELS[k])}</b>'
        f'<span>{escape(service.PERSONA_DESCRIPTIONS[k])} · profil fictif</span></a></li>' for k in service.persona_keys())
    body = ('<section><h1>Choisissez un profil fictif</h1>'
            '<p class="lead">L’agent compare le risque d’une action à la tolérance au risque de ce profil, puis explique le résultat.</p>'
            f'<ul class="cards">{cards}</ul></section>')
    return shell("Peace · choix du profil", body)


def error_page(message: str, persona: str | None = None, status_hint: str = "Erreur") -> str:
    body = f'<section><h1>{escape(status_hint)}</h1><p class="banner err" role="alert">{escape(message)}</p><p><a href="/">Retour à l’accueil</a></p></section>'
    return shell(status_hint, body, persona)


def home(persona: str, profile: dict, amount: float) -> str:
    rows = "".join(
        f'<tr><td><a href="/asset/{escape(quote(t, safe=""))}?{_q(u=persona)}"><span translate="no">{escape(t)}</span></a></td>'
        f'<td translate="no">{escape(n)}</td><td>{escape(c)}</td></tr>' for t, n, c in service.universe_tickers())
    body = (f'<section><h1>Profil de {escape(service.PERSONA_LABELS[persona])}</h1>'
            f'<p class="lead">Tolérance au risque : {escape(str(profile["final_score_display"]))} sur 100 · confiance {escape(profile["confidence"]["label"])}.</p>'
            '<p>Ouvrez la page d’une action : l’agent calcule alors son score, le verdict et le rapport. Rien ne tourne avant.</p>'
            '<div class="table-scroll" tabindex="0" role="region" aria-label="Liste des actions (défilable)"><table>'
            '<thead><tr><th scope="col">Titre</th><th scope="col">Nom</th><th scope="col">Classe</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></section>')
    return shell("Actions · Peace", body, persona)


def profile_page(persona: str, profile: dict, purchases: list[dict], notice: str = "") -> str:
    comps = "".join(f"<tr><td>{escape(str(c.get('label', c.get('key', ''))))}</td><td>{escape(str(c.get('score', '')))}</td>"
                    f"<td>{escape(str(c.get('weight', '')))}</td></tr>" for c in _component_rows(profile))
    if purchases:
        plist = "".join(f'<tr><td>{escape(p["date"])}</td><td translate="no">{escape(p["ticker"])}</td>'
                        f'<td>{escape(f"{p["amount_cad"]:.2f}".replace(".", ","))} $ CAD</td></tr>' for p in purchases)
        ptable = ('<div class="table-scroll" tabindex="0" role="region" aria-label="Achats simulés (défilable)"><table><thead><tr>'
                  '<th scope="col">Date</th><th scope="col">Titre</th><th scope="col">Montant</th></tr></thead>'
                  f'<tbody>{plist}</tbody></table></div>')
        reset = (f'<form class="box" method="post" action="/reinitialiser"><input type="hidden" name="u" value="{escape(persona)}">'
                 '<button class="btn ghost" type="submit">Effacer mes achats simulés</button></form>')
    else:
        ptable, reset = "<p>Aucun achat simulé pour l’instant.</p>", ""
    note = f'<p class="banner" role="status">{escape(notice)}</p>' if notice else ""
    body = (f'<section><h1>Profil de {escape(service.PERSONA_LABELS[persona])}</h1>{note}'
            f'<dl class="kv"><dt>Tolérance au risque</dt><dd>{escape(str(profile["final_score_display"]))} sur 100</dd>'
            f'<dt>Confiance</dt><dd>{escape(profile["confidence"]["label"])}</dd>'
            f'<dt>Opérations prises en compte</dt><dd>{escape(str(profile["history"]["n_valid_trades"]))}</dd></dl></section>'
            f'<section><h2>Achats simulés</h2><p>Ils s’ajoutent à l’historique du profil et font évoluer son score.</p>{ptable}{reset}</section>'
            f'<section><h2>Composantes du score</h2><div class="table-scroll" tabindex="0" role="region" aria-label="Composantes (défilable)"><table>'
            f'<thead><tr><th scope="col">Composante</th><th scope="col">Score</th><th scope="col">Poids</th></tr></thead><tbody>{comps}</tbody></table></div></section>')
    return shell("Profil · Peace", body, persona)


def _component_rows(profile: dict) -> list[dict]:
    labels = {"history": "Historique des opérations", "quiz": "Quiz", "situations": "Mises en situation"}
    return [{"label": labels.get(k, k), "score": f'{v["score"]:.1f}'.replace(".", ","),
             "weight": f'{round(v["effective_weight"] * 100)} %'} for k, v in profile["components"].items()]


def purchase_result(persona: str, ticker: str, result: dict) -> str:
    entry, before, after = result["entry"], result["before"], result["after"]
    qty = f'{entry["quantity"]:.4f}'.rstrip("0").rstrip(".").replace(".", ",")
    body = (f'<section><h1>Achat simulé enregistré</h1>'
            f'<p class="banner" role="status">Simulation : aucune transaction réelle n’a eu lieu et aucun argent n’a été engagé.</p>'
            f'<p>{escape(qty)} part(s) de <span translate="no">{escape(ticker)}</span> pour {escape(f"{entry["amount_cad"]:.2f}".replace(".", ","))} $ CAD '
            f'au prix de clôture du {escape(entry["date"])}.</p>'
            '<h2>Effet sur votre profil</h2>'
            f'<dl class="kv"><dt>Tolérance avant</dt><dd>{escape(str(before["final_score_display"]))} sur 100</dd>'
            f'<dt>Tolérance après</dt><dd>{escape(str(after["final_score_display"]))} sur 100</dd>'
            f'<dt>Confiance après</dt><dd>{escape(after["confidence"]["label"])}</dd></dl>'
            f'<p class="hint">Le score est recalculé de zéro, avec les mêmes règles, sur l’historique et vos achats simulés.</p>'
            f'<p class="row"><a class="btn" href="/profil?{_q(u=persona)}">Voir mon profil</a>'
            f'<a class="btn ghost" href="/?{_q(u=persona)}">Retour aux actions</a></p></section>')
    return shell("Achat simulé · Peace", body, persona)


# ----------------------------------------------------------------- page d'une action


def _sentences(sentences: list[dict]) -> str:
    return "".join(f"<p>{escape(s['text'])}"
                   f"{' <span class=\"tag\">[' + escape(', '.join(s['facts'])) + ']</span>' if s['facts'] else ''}</p>" for s in sentences)


def answer_box(answer: dict | None, title: str = "") -> str:
    if not answer:
        return '<div id="reponse" aria-live="polite"></div>'
    kinds = {"preset": "Réponse préparée, sans IA : textes issus des faits du rapport.",
             "agent": "Réponse de l’agent (Strands, Amazon Bedrock), vérifiée : chaque nombre et chaque fait cité existe.",
             "refus": "Refus : cet outil ne donne pas de conseil d’achat ou de vente.",
             "echec": "Réponse non vérifiable : rien n’est affiché de ce que le modèle a écrit.",
             "invalide": "Question refusée."}
    err = f'<p class="banner err" role="alert">{escape(answer["error"])}</p>' if answer.get("kind") == "invalide" else ""
    calls = ""
    if answer.get("tool_log"):
        items = "".join(f'<li><code>{escape(t["tool"])}({escape(str(t["args"]))})</code></li>' for t in answer["tool_log"])
        calls = f'<details><summary>Outils consultés par l’agent</summary><ul class="notes">{items}</ul></details>'
    extra = ""
    if answer.get("extra_facts"):
        rows = "".join(f'<li><b>{escape(f.id)}</b> {escape(f.text)}</li>' for f in answer["extra_facts"])
        extra = f'<details><summary>Faits créés pour cette réponse</summary><ul class="notes">{rows}</ul></details>'
    return (f'<div id="reponse" class="answer" aria-live="polite"><h3>{escape(title or "Réponse")}</h3>{err}'
            f'{_sentences(answer.get("sentences", []))}<p class="tag">{escape(kinds.get(answer.get("kind"), ""))}</p>{calls}{extra}</div>')


def _num(x: float, decimals: int) -> str:
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",")


def fx_line(fx: dict | None) -> str:
    """Conversion du montant au taux du jour (affichée sous le champ du montant)."""
    if not fx:
        return ""
    return f'<p class="fx">≈ <b>{_num(fx["amount_usd"], 2)} $ US</b> au taux du jour</p>'


def fx_sources(fx: dict | None) -> str:
    """Petit « + Sources » en bas de page : d'où vient le taux et de quand il date."""
    if not fx:
        return ""
    change = ""
    if fx.get("change_pct") is not None:
        chg = f'{fx["change_pct"]:+.2f}'.replace(".", ",")
        change = (f' Les données du projet utilisent {_num(fx["reference_rate"], 4)} au {escape(fx["reference_date"])} '
                  f'({chg} %).')
    return (f'<details class="src"><summary>Sources</summary><p>Taux USD/CAD : 1 $ US = {_num(fx["rate"], 4)} $ CAD '
            f'({escape(fx["date"])}), {escape(fx["source"])}, relevé le {escape(fx.get("retrieved_at", "date inconnue"))}.{change} '
            'Ce taux sert à convertir le montant ; il ne modifie pas le score de risque.</p></details>')


def purchase_block(persona: str, ticker: str, amount: float, notice: str = "", fx: dict | None = None) -> str:
    """Premier bloc sous le verdict : montant, « Simuler l'achat ». Aucune case à cocher."""
    amt = fmt_amount(amount)
    notice_html = f'<p class="banner warn" role="alert">{escape(notice)}</p>' if notice else ""
    return f"""<section id="achat" class="buy" aria-labelledby="h-achat">
<h2 id="h-achat">Simuler un achat</h2>{notice_html}
<form class="box" method="post" action="/achat">
<input type="hidden" name="u" value="{escape(persona)}"><input type="hidden" name="ticker" value="{escape(ticker)}">
<label for="amount">Montant (CAD)
<input id="amount" name="amount" type="text" inputmode="decimal" autocomplete="off" value="{escape(amt)}" required></label>
{fx_line(fx)}
<span class="row"><button class="btn" type="submit">Simuler l’achat</button>
<button class="btn ghost" type="submit" formmethod="get" formaction="/asset/{escape(quote(ticker, safe=''))}">Recalculer le verdict</button></span>
<p class="hint">Simulation : aucune transaction réelle, ni conseil. L’achat simulé est inscrit dans un registre fictif et fait évoluer votre profil.</p></form>
</section>"""


def _fr1(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def news_block(news: dict | None, persona: str, ticker: str, amount: float) -> str:
    """Panneau « Actualité » (agent filtreur). Tout texte externe est échappé."""
    refresh = (f'<a class="btn ghost" href="/asset/{escape(quote(ticker, safe=""))}?'
               f'{_q(u=persona, amount=fmt_amount(amount), refresh="1", more="1")}#actualite">Actualiser l’actualité</a>')
    body = ""
    if news is None:
        body = "<p>La lecture de l’actualité est désactivée dans cette session.</p>"
    else:
        status = news.get("status")
        sources = "".join(
            f'<li><b>{escape(s["name"])}</b> <span class="tag">{escape(s["orientation"])}</span> : '
            f'{escape(news.get("sources", {}).get(s["id"], "non consultée"))}</li>' for s in config.NEWS_SOURCES)
        if status == "indisponible":
            body = ('<p class="banner warn" role="status">L’actualité n’a pas pu être analysée '
                    f'({escape(str(news.get("error") or "panne"))}). Le verdict ne repose que sur les prix.</p>')
        elif status == "en_cours":
            body = ('<p class="banner warn" role="status">L’analyse de l’actualité est encore en cours : pour l’instant, le verdict ne repose '
                    'que sur les prix. Cliquez sur « Actualiser l’actualité » dans quelques secondes pour l’intégrer.</p>')
        elif status == "aucune":
            body = "<p>Aucun article récent sur cette action dans les sources suivies : le verdict ne repose que sur les prix.</p>"
        else:
            groups = {g["type"]: g for g in news.get("groups", [])}
            adj = float(news.get("adjustment", 0))
            head = (f"<p>Effet de l’actualité sur le risque de l’action : <b>+{_fr1(adj)} point(s)</b> "
                    f"(plafond {_fr1(config.NEWS_MAX_POINTS)}). "
                    f"{len(news.get('read', []))} article(s) ouvert(s) par l’agent sur {len(news.get('considered', []))} retenu(s).</p>")
            n_ev = len(news.get("events", []))
            vol = news.get("volume") or {}
            if vol.get("points"):
                head += (f'<p class="banner warn" role="status">Règle du nombre : {int(vol["n_articles"])} articles défavorables distincts '
                         f'(sources non confirmées entre elles) ajoutent <b>{_fr1(vol["points"])} point(s)</b>.</p>')
            elif adj == 0 and n_ev:
                head += (f'<p class="banner warn" role="status">Pourquoi aucun effet : l’agent a repéré {n_ev} événement(s) défavorable(s), '
                         'mais chacun n’apparaît que dans une seule source et leur nombre reste sous le seuil '
                         f'({config.NEWS_VOLUME_POINTS[-1][0]} articles). Il faut 2 sources distinctes sur le même événement, '
                         'ou beaucoup d’articles défavorables, pour que le score bouge.</p>')
            if news.get("extra_margin"):
                head += ('<p class="banner warn" role="status">Les sources divergent sur la gravité : le score ne bouge pas davantage, '
                         f'mais la marge d’incertitude du verdict est élargie de {_fr1(config.NEWS_DIVERGENCE_MARGIN)} points.</p>')
            items = ""
            for e in news.get("events", []):
                g = groups.get(e["type"], {})
                state = (f'confirmé par {g.get("n_sources", 0)} sources' if g.get("corroborated")
                         else "non confirmé : aucun effet sur le score")
                items += (f'<li><p><b>{escape(config.NEWS_EVENT_TYPES.get(e["type"], e["type"]))}</b> · gravité {int(e["severity"])}/3 · {escape(state)}<br>'
                          f'<span class="tag">{escape(e["source_name"])} ({escape(e["orientation"])})</span> '
                          f'<a href="{escape(e["link"])}" target="_blank" rel="noopener noreferrer">{escape(e["title"])}</a></p>'
                          f'<blockquote>« {escape(e["quote"])} »</blockquote>'
                          f'<p class="hint">Résumé de l’agent : {escape(e["summary"])}</p></li>')
            body = head + (f'<ul class="events">{items}</ul>' if items else
                           "<p>Aucun événement qui relève le risque n’a été retenu.</p>")
            if news.get("rejected"):
                body += (f'<p class="hint">{len(news["rejected"])} événement(s) proposé(s) par l’agent ont été rejetés par la vérification '
                         '(citation introuvable, type invalide…).</p>')
        body += f'<details><summary>Sources suivies</summary><ul>{sources}</ul></details>'
        if news.get("retrieved_at"):
            body += f'<p class="hint">Instantané du {escape(news["retrieved_at"])} ; la page reste identique tant qu’on n’actualise pas.</p>'
    return (f'<section id="actualite" aria-labelledby="h-actu"><h2 id="h-actu">Actualité récente</h2>'
            f'<p class="hint">Un agent (Amazon Bedrock + Strands) lit les articles et ne retient que ce qui relève le risque ; '
            f'des règles fixes calculent les points. Étiquettes gauche / neutre / droite : orientation éditoriale généralement attribuée.</p>'
            f'{body}<p>{refresh}</p></section>')


def questions_block(persona: str, ticker: str, amount: float, answer: dict | None, remaining_questions: int) -> str:
    amt = fmt_amount(amount)
    hidden = (f'<input type="hidden" name="u" value="{escape(persona)}"><input type="hidden" name="ticker" value="{escape(ticker)}">')
    base = {"u": persona, "amount": amt}
    return f"""<section id="pourquoi-suivi" aria-labelledby="h-suivi">
<h2 id="h-suivi">Pourquoi ? Posez une question</h2>
<p class="row">
<a class="btn ghost" href="/asset/{escape(quote(ticker, safe=''))}?{_q(**base, q='why')}#reponse">Pourquoi cette couleur ?</a>
<a class="btn ghost" href="/asset/{escape(quote(ticker, safe=''))}?{_q(**base, q='profile')}#reponse">Qu’est-ce qui pèse dans mon profil ?</a>
<a class="btn ghost" href="/asset/{escape(quote(ticker, safe=''))}?{_q(**base, q='scenario')}#reponse">Et si le montant changeait ?</a></p>
<form class="box" method="post" action="/question">{hidden}<input type="hidden" name="amount" value="{escape(amt)}">
<label for="question">Question libre (agent Strands)
<textarea id="question" name="question" rows="3" maxlength="{config.FOLLOWUP_MAX_QUESTION_CHARS}" autocomplete="off" placeholder="Par exemple : que signifie la baisse maximale ?…"></textarea></label>
<button class="btn" type="submit">Poser la question</button>
<p class="hint">{remaining_questions} question(s) libre(s) restante(s) pour cette action. Pas de conseil d’achat ou de vente.</p></form>
{answer_box(answer, "Réponse")}
</section>"""


# ------------------------------------------------------------ mise en situation (avant le verdict)


def _radio(name: str, value: str, label: str, checked: bool = False) -> str:
    return (f'<label class="check"><input type="radio" name="{escape(name)}" value="{escape(value)}" required'
            f'{" checked" if checked else ""}><span>{escape(label)}</span></label>')


def _yes_no_row(group: str, text: str, yes: str, no: str, first: bool = False) -> str:
    label_id = f"lbl-{group}"
    return (f'<div class="qrow" role="radiogroup" aria-labelledby="{label_id}"><span id="{label_id}">{escape(text)}</span>'
            f'<span class="qopts"><label class="pill"><input type="radio" name="{group}" value="oui" required{" autofocus" if first else ""}>'
            f'<span>{escape(yes)}</span></label>'
            f'<label class="pill"><input type="radio" name="{group}" value="non" required><span>{escape(no)}</span></label></span></div>')


def amount_step_page(persona: str, ticker: str, asset_name: str, amount: float, error: str = "") -> str:
    """Première ouverture d'une action : on demande d'abord le montant, la mise en situation vient ensuite."""
    err = f'<p class="banner err" role="alert">{escape(error)}</p>' if error else ""
    body = f"""<section><h1><span translate="no">{escape(asset_name)} ({escape(ticker)})</span></h1>
<p class="lead">Quel montant envisagez-vous d’investir ? Il sert à poser les mises en situation, puis à calculer le verdict.</p>{err}
<form class="box" method="get" action="/asset/{escape(quote(ticker, safe=''))}">
<input type="hidden" name="u" value="{escape(persona)}">
<label for="amount">Montant (CAD)
<input id="amount" name="amount" type="text" inputmode="decimal" autocomplete="off" value="{escape(fmt_amount(amount))}" required autofocus></label>
<button class="btn" type="submit">Continuer</button>
<p class="hint">Simulation : aucune transaction réelle, ni conseil.</p></form></section>"""
    return shell("Montant · Peace", body, persona)


def situation_page(persona: str, ticker: str, asset_name: str, amount: float, error: str = "") -> str:
    """Page de l'action avec la mise en situation en POP-UP. Le verdict n'est PAS rendu derrière :
    le fond ne contient que le nom de l'action, et il est inerte (ni clic ni tabulation)."""
    texts = situations.scenario_texts(asset_name, ticker, amount)
    ladder = "".join(_yes_no_row(f"ladder_{i}", l["text"], "Oui", "Non", first=(i == 0))
                     for i, l in enumerate(texts["ladder"]["levels"]))
    reaction = "".join(_radio("reaction", str(i), o) for i, o in enumerate(texts["reaction"]["options"]))
    tradeoff = "".join(_yes_no_row(f"tradeoff_{i}", o["text"], "J’accepte", "Je refuse")
                       for i, o in enumerate(texts["tradeoff"]["options"]))
    err = f'<p class="banner err" role="alert">{escape(error)}</p>' if error else ""
    back = f"""<div inert aria-hidden="true"><section><h1><span translate="no">{escape(asset_name)} ({escape(ticker)})</span></h1>
<p class="lead">Le verdict s’affichera après la mise en situation.</p></section></div>"""
    modal = f"""<div class="backdrop"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="m-title" aria-describedby="m-desc">
<h2 id="m-title">Avant le verdict : une mise en situation</h2>
<p id="m-desc" class="hint">Trois situations imaginaires pour <span translate="no">{escape(asset_name)} ({escape(ticker)})</span>. Elles servent à calculer votre tolérance au risque avec votre historique. Ce n’est pas un conseil et aucun argent n’est engagé.</p>
{err}
<form method="post" action="/situation">
<input type="hidden" name="u" value="{escape(persona)}"><input type="hidden" name="ticker" value="{escape(ticker)}">
<input type="hidden" name="amount" value="{escape(fmt_amount(amount))}">
<h3>1. Jusqu’où iriez-vous ?</h3><p class="hint">{escape(texts["ladder"]["intro"])}</p>{ladder}
<h3>2. Après une baisse</h3>
<fieldset class="q"><legend>{escape(texts["reaction"]["text"])}</legend>{reaction}</fieldset>
<h3>3. Deux issues possibles</h3><p class="hint">{escape(texts["tradeoff"]["intro"])}</p>{tradeoff}
<div class="row mfoot"><button class="btn" type="submit" name="action" value="answer">Valider mes réponses</button>
<button class="btn ghost" type="submit" name="action" value="skip" formnovalidate>Passer cette étape</button></div>
<p class="hint">Passer est possible : votre tolérance s’appuie alors sur moins d’informations et la confiance baisse.</p>
</form></div></div>"""
    html = shell("Mise en situation · Peace", back, persona)
    return html.replace("</body>", modal + "\n</body>", 1)
