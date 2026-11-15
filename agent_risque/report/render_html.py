"""Rapport HTML autonome : CSS et SVG intégrés, sans JavaScript, sans requête externe.

Mise en page : une colonne, bords égaux, polices du système, thème clair et sombre, aucune
légende sous les graphiques (un intertitre au-dessus, le tableau équivalent dans un bloc
dépliable). Chaque phrase du rapport renvoie à son fait (numéro cliquable).
"""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

from .. import asset_score, combine, comparison, config, data_access
from ..asset_score import AssetRiskResult
from . import charts
from .build import build_report
from .facts import fr

GLYPH = {"vert": "●", "jaune": "▲", "rouge": "■"}
STATUS_LABEL = {
    "ok": ("✓", "Respectée"), "attention": ("▲", "Attention"), "violation": ("■", "Non respectée"),
    "non_evaluee": ("–", "Non évaluée"), "non_verifiable": ("?", "Pas de données"),
}

CSS = """
:root{color-scheme:light dark;--bg:#f7f7f4;--surface:#fff;--ink:#16181d;--muted:#566070;--line:#d8dce3;
--accent:#1f4fd8;--on-accent:#fff;--track:#e7e9ee;--bar:#6b7384;--seg-b:#4b5262;--bad:#b3261e;
--zone-green:#d6ecdd;--zone-yellow:#f6e8b8;--zone-red:#f3d0cc;
--ok:#14683f;--warn:#7a5600;--no:#a3201a;--radius:12px;--space:clamp(16px,4vw,32px)}
@media (prefers-color-scheme:dark){:root{--bg:#101216;--surface:#181b21;--ink:#eceef2;--muted:#a3aab8;--line:#2d323c;
--accent:#7aa2ff;--on-accent:#0b0d12;--track:#262b34;--bar:#8d95a6;--seg-b:#3a4150;--bad:#ff8a80;
--zone-green:#1d3a2b;--zone-yellow:#3d3418;--zone-red:#4a2321;--ok:#7bd3a0;--warn:#e8c765;--no:#ff9a92}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;-webkit-tap-highlight-color:transparent}
a,summary{touch-action:manipulation}
h2,tr[id],section[id]{scroll-margin-top:24px}
.top,main section,footer{padding-inline:env(safe-area-inset-left) env(safe-area-inset-right)}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
font-variant-numeric:tabular-nums}
.wrap{max-width:880px;margin-inline:auto;padding-inline:var(--space)}
.skip{position:absolute;left:var(--space);top:-60px;background:var(--ink);color:var(--bg);padding:10px 14px;border-radius:8px;z-index:10}
.skip:focus{top:12px}
a{color:var(--accent);text-underline-offset:3px}
:focus-visible{outline:3px solid var(--accent);outline-offset:3px;border-radius:4px}
.top{padding-block:clamp(32px,8vw,72px) clamp(20px,4vw,36px);border-bottom:1px solid var(--line)}
.eyebrow{margin:0 0 8px;color:var(--muted);font-size:14px;letter-spacing:.02em}
h1{margin:0 0 20px;font-size:clamp(28px,5.2vw,44px);line-height:1.12;letter-spacing:-.02em;text-wrap:balance}
h2{margin:0 0 14px;font-size:clamp(21px,3vw,26px);line-height:1.2;letter-spacing:-.01em;text-wrap:balance}
h3{margin:22px 0 8px;font-size:16px;font-weight:600}
.verdict{display:flex;flex-wrap:wrap;align-items:center;gap:12px 16px;margin:0}
.badge{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border-radius:999px;font-weight:700;
border:2px solid var(--ink);background:var(--surface)}
.badge-vert{background:var(--zone-green)}.badge-jaune{background:var(--zone-yellow)}.badge-rouge{background:var(--zone-red)}
.lead{font-size:18px;max-width:56ch}
main section{padding-block:clamp(28px,5vw,48px);border-bottom:1px solid var(--line)}
main section:last-child{border-bottom:0}
p{margin:0 0 12px;max-width:68ch}
.sentence{display:inline}
.cite{font-size:11px;margin-left:2px;vertical-align:super;line-height:0}
.cite a{text-decoration:none;color:var(--muted);padding:0 2px;background:linear-gradient(currentColor,currentColor) 0 100%/0 1px no-repeat;
transition:background-size .2s ease,color .2s ease}
.cite a:hover{color:var(--accent);background-size:100% 1px}
.chart{margin-top:18px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px;
transition:border-color .2s ease,transform .2s ease}
.chart:hover{border-color:var(--muted);transform:translateY(-2px)}
.chart h3{margin-top:0}
.chart-scroll{overflow-x:auto;overscroll-behavior-x:contain}
.chart-svg{display:block;width:100%;min-width:600px;height:auto;font-family:inherit}
.zone-green{fill:var(--zone-green)}.zone-yellow{fill:var(--zone-yellow)}.zone-red{fill:var(--zone-red)}
.zone-label{fill:var(--ink);font-size:13px;font-weight:600}
.marker-user{stroke:var(--ink);stroke-width:3}.dashed{stroke-dasharray:5 4;stroke-width:2}
.marker-asset{fill:var(--accent)}
.bar{fill:var(--bar)}.bar-over{fill:var(--accent)}.bar-track{fill:var(--track)}
.seg-a{fill:var(--accent)}.seg-b{fill:var(--seg-b)}.seg-text-a{fill:var(--on-accent);font-size:13px;font-weight:600}
.seg-text-b{fill:#fff;font-size:13px;font-weight:600}
.label,.value{fill:var(--ink);font-size:14px}.label-strong{fill:var(--ink);font-size:14px;font-weight:600}
.muted{fill:var(--muted);font-size:14px}.axis{fill:var(--muted);font-size:12px}
.tick{stroke:var(--muted);stroke-width:1}.axis-line{stroke:var(--muted);stroke-width:1}.grid{stroke:var(--line);stroke-width:1}
.dot{fill:var(--muted);opacity:.75;stroke:var(--surface);stroke-width:1}
.dot-selected{fill:var(--accent);stroke:var(--surface);stroke-width:2}
.dot-peak{fill:var(--surface);stroke:var(--ink);stroke-width:2}
.price-line{stroke:var(--ink);stroke-width:2;stroke-linejoin:round}.drawdown{stroke:var(--bad);stroke-width:2;stroke-dasharray:4 3}
details{margin-top:12px}
summary{cursor:pointer;color:var(--accent);padding:6px 0;font-size:14px;transition:color .2s ease}
summary:hover{text-decoration:underline}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:6px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}
.table-scroll{overflow-x:auto}
ul.status,ul.notes{margin:12px 0 0;padding:0;list-style:none;display:grid;gap:8px}
ul.status li{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}
.status-chip{font-weight:600;white-space:nowrap}
.s-ok{color:var(--ok)}.s-attention{color:var(--warn)}.s-violation{color:var(--no)}.s-non_evaluee,.s-non_verifiable{color:var(--muted)}
ul.notes li{padding-left:18px;position:relative;max-width:68ch}
p.fine{margin:12px 0 0;font-size:.8125rem;color:var(--muted);max-width:68ch}
ul.notes li::before{content:"";position:absolute;left:0;top:.7em;width:8px;height:2px;background:var(--muted)}
ol.trace{margin:8px 0 0;padding-left:22px;display:grid;gap:10px;max-width:72ch}
.trace b{display:block}
.trace .mod{color:var(--muted);font-size:13px}
footer{padding-block:28px 56px;color:var(--muted);font-size:14px}
footer p{max-width:72ch}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.top .wrap>*{animation:rise .5s ease both}.top .wrap>*:nth-child(2){animation-delay:.06s}.top .wrap>*:nth-child(3){animation-delay:.12s}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
@media print{body{background:#fff}.chart{break-inside:avoid}.skip{display:none}}
"""

_CHARTS_FOR = {"en_bref": ["gap"], "pourquoi": ["components"], "profil": ["profile"], "action": ["price", "universe"]}


def _sentences_html(sentences: list[dict]) -> str:
    parts = []
    for s in sentences:
        cites = "".join(f'<sup class="cite"><a href="#f{escape(i[1:])}" aria-label="Fait {escape(i[1:])}">{escape(i[1:])}</a></sup>'
                        for i in s["facts"])
        parts.append(f'<span class="sentence">{escape(s["text"])}{cites}</span>')
    return "<p>" + " ".join(parts) + "</p>" if parts else ""


def _table_html(table: dict) -> str:
    head = "".join(f"<th scope=\"col\">{escape(h)}</th>" for h in table["headers"])
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in table["rows"])
    return (f'<div class="table-scroll" tabindex="0" role="region" aria-label="Tableau des valeurs (défilable)">'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')


def _chart_html(chart: dict) -> str:
    return (f'<div class="chart"><h3>{escape(chart["title"])}</h3>'
            f'<div class="chart-scroll" tabindex="0" role="region" aria-label="{escape(chart["title"])} (défilable)">{chart["svg"]}</div>'
            f'<details><summary>Voir les valeurs du graphique</summary>{_table_html(chart["table"])}</details></div>')


def render_report(result: dict, verdict: dict, profile: dict, asset: AssetRiskResult,
                  universe_scores: dict[str, float], nav_html: str = "", before_trace_html: str = "",
                  extra_css: str = "", top_html: str = "", collapse: bool = False, open_more: bool = False,
                  simple_lead: str = "", bottom_html: str = "") -> str:
    """nav_html / before_trace_html / extra_css : points d'insertion pour la page de démonstration (étape 5).
    top_html : bloc placé juste sous le verdict (achat simulé). collapse : tout le détail (scores, comparaison,
    graphiques, trace) est replié derrière « En savoir plus » ; open_more le garde ouvert."""
    sheet = result["sheet"]
    color = verdict["final_color"]
    chart_map = {
        "gap": charts.gap_chart(verdict),
        "components": charts.components_chart(verdict),
        "profile": charts.profile_chart(profile),
        "price": charts.price_chart(asset),
        "universe": charts.universe_chart(verdict, universe_scores),
    }
    sections = []
    for section in result["report"]["sections"]:
        sid = section["id"]
        inner = [f'<h2 id="h-{sid}">{escape(section["title"])}</h2>']
        if sid != "limites":                      # « Ce qu'il faut savoir » : seulement la petite ligne ci-dessous
            inner.append(_sentences_html(section["sentences"]))
        if sid == "contraintes":
            items = []
            for c in verdict["constraints"]:
                glyph, label = STATUS_LABEL[c["status"]]
                items.append(f'<li><span class="status-chip s-{c["status"]}"><span aria-hidden="true">{glyph}</span> {label}</span>'
                             f'<span>{escape(c["label"])}</span></li>')
            inner.append('<ul class="status">' + "".join(items) + "</ul>")
        for key in _CHARTS_FOR.get(sid, []):
            inner.append(_chart_html(chart_map[key]))
        if sid == "limites":
            inner.append('<p class="fine">' + " · ".join(escape(d) for d in asset.disclaimers) + "</p>")
        sections.append(f'<section id="{sid}" aria-labelledby="h-{sid}">' + "".join(inner) + "</section>")

    trace_items = "".join(f'<li><b>{escape(t["step"])}</b><span>{escape(t["detail"])}</span> '
                          f'<span class="mod">({escape(t["module"])})</span></li>' for t in result["trace"])
    type_label = {"donnee": "Donnée", "calcul": "Calcul", "hypothese": "Hypothèse", "limite": "Limite"}
    fact_rows = "".join(
        f'<tr id="f{escape(f.id[1:])}"><td>{escape(f.id[1:])}</td><td>{type_label[f.type]}</td>'
        f'<td>{escape(f.text_for(sheet.level))}</td><td>{escape(f.source)}</td></tr>' for f in sheet.facts)
    facts_table = ('<div class="table-scroll"><table><thead><tr><th scope="col">N°</th><th scope="col">Type</th>'
                   '<th scope="col">Fait</th><th scope="col">Source</th></tr></thead><tbody>' + fact_rows + "</tbody></table></div>")
    prices = next((s for s in asset.data_sources if s["file"] == "prices_daily.csv"), None)
    foot_source = (f"Prix : {prices['source']}, extraction du {prices['retrieved_on']}. " if prices else "")
    headline = result["report"]["sections"][0]["sentences"][0]["text"] if result["report"]["sections"][0]["sentences"] else ""
    title = f"{asset.ticker} et votre profil : rapport de simulation"
    desc = f"Adéquation entre le risque de {asset.name} et un profil fictif, au {verdict['as_of']}. Simulation, aucun conseil financier."

    more_open = more_close = ""
    if collapse:
        more_open = ('<details class="more" id="en-savoir-plus"' + (" open" if open_more else "") + '>'
                     '<summary>En savoir plus : scores et comparaison des tolérances</summary>'
                     '<div class="more-body">')
        more_close = "</div></details>"

    return f"""<!doctype html>
<html lang="fr" data-verdict="{color}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f7f7f4" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#101216" media="(prefers-color-scheme: dark)">
<style>{CSS}{extra_css}</style>
</head>
<body>
<a class="skip" href="#contenu">Passer au contenu</a>
{nav_html}
<header class="top"><div class="wrap">
<p class="eyebrow">Simulation · {escape(verdict['as_of'])} · profil {escape(verdict['user_id'])}</p>
<h1><span translate="no">{escape(asset.name)} ({escape(asset.ticker)})</span> face à votre profil</h1>
<p class="verdict"><span class="badge badge-{color}"><span aria-hidden="true">{GLYPH[color]}</span> Verdict {color}</span>
<span class="lead">{escape(simple_lead or headline)}</span></p>
</div></header>
<main id="contenu" class="wrap">
{top_html}
{more_open}{"".join(sections)}
{before_trace_html}
<section id="trace" aria-labelledby="h-trace">
<h2 id="h-trace">Comment ce résultat a été calculé</h2>
<ol class="trace">{trace_items}</ol>
<details><summary>Voir les {len(sheet.facts)} faits et leurs sources</summary>{facts_table}</details>
</section>
{more_close}{bottom_html}</main>
<footer><div class="wrap"><p>Simulation uniquement : aucune transaction réelle et aucun conseil financier personnalisé. {escape(foot_source)}Les performances passées ne prédisent pas l’avenir.</p></div></footer>
</body>
</html>
"""


def make_report_page(profile: dict, ticker: str, as_of: date | None = None, planned_amount_cad: float | None = None,
                     level: str | None = None, mode: str = "template", client=None, cache_dir=None) -> tuple[str, dict]:
    """Chaîne complète pour l'ouverture d'une page d'action : score, verdict, rapport, HTML."""
    as_of = as_of or date.fromisoformat(profile["as_of"])
    asset = asset_score.score_asset(ticker, as_of)
    verdict = comparison.compare(profile, asset, planned_amount_cad)
    result = build_report(verdict, profile, asset, level=level, mode=mode, client=client, cache_dir=cache_dir)
    universe = {t: asset_score.score_asset(t, as_of).score for t in data_access.load_universe()}
    return render_report(result, verdict, profile, asset, universe), {"verdict": verdict, "result": result, "asset": asset}


def write_report(path: Path | str, html_text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8", newline="\n")
    return path
