"""Graphiques SVG (stdlib seulement), déterministes et accessibles.

Chaque graphique renvoie {"svg", "title", "table"}: un SVG en ligne stylé par les classes
CSS de la page (thème clair et sombre), un titre, et le tableau de données équivalent.
La couleur ne porte jamais seule l'information : zones nommées, glyphes, valeurs écrites.
Aucune légende sous le graphique : le titre est un intertitre de la page.
"""

from __future__ import annotations

from html import escape

from .. import combine, data_access
from ..asset_score import AssetRiskResult
from .facts import fr

W = 720
X0, X1 = 40.0, 680.0           # 0 -> 100 sur l'axe horizontal des graphiques en bandes


def _x(v: float) -> float:
    return X0 + (X1 - X0) * max(0.0, min(100.0, v)) / 100.0


def _n(x: float) -> str:
    return f"{x:.1f}"


def _svg(height: int, title: str, desc: str, body: str, width: int = W) -> str:
    return (f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" '
            f'aria-labelledby="t{abs(hash_id(title))} d{abs(hash_id(title))}" '
            f'preserveAspectRatio="xMidYMid meet">'
            f'<title id="t{abs(hash_id(title))}">{escape(title)}</title>'
            f'<desc id="d{abs(hash_id(title))}">{escape(desc)}</desc>{body}</svg>')


def hash_id(text: str) -> int:
    """Identifiant numérique stable (hash() de Python varie d'une exécution à l'autre)."""
    h = 0
    for ch in text:
        h = (h * 131 + ord(ch)) % 1_000_003
    return h


def _anchor(x: float, text: str) -> str:
    """Ancrage du texte pour qu'il reste dans le cadre près des bords."""
    width = 7.2 * len(text)
    if x - width / 2 < 6:
        return "start"
    if x + width / 2 > W - 6:
        return "end"
    return "middle"


def gap_chart(verdict: dict) -> dict:
    """Échelle 0-100 : zones vert/jaune/rouge autour de la tolérance, repère de l'action."""
    tol, score = verdict["user"]["effective_tolerance"], verdict["asset"]["score"]
    thr = verdict["thresholds"]
    g_end, y_end = tol + thr["green_max_gap"], tol + thr["yellow_max_gap"]
    zones = [("vert", "zone-green", 0.0, g_end, "Vert"), ("jaune", "zone-yellow", g_end, y_end, "Jaune"),
             ("rouge", "zone-red", y_end, 100.0, "Rouge")]
    body = []
    for _, cls, lo, hi, label in zones:
        lo_c, hi_c = max(0.0, lo), min(100.0, hi)
        if hi_c <= lo_c:
            continue
        w = _x(hi_c) - _x(lo_c)
        body.append(f'<rect class="{cls}" x="{_n(_x(lo_c))}" y="44" width="{_n(w)}" height="30"/>')
        if w >= 58:
            body.append(f'<text class="zone-label" x="{_n(_x(lo_c) + w / 2)}" y="63" text-anchor="middle">{label}</text>')
    for tick in (0, 25, 50, 75, 100):
        body.append(f'<line class="tick" x1="{_n(_x(tick))}" y1="74" x2="{_n(_x(tick))}" y2="79"/>'
                    f'<text class="axis" x="{_n(_x(tick))}" y="94" text-anchor="middle">{tick}</text>')
    # Tolérance : barre qui traverse la bande, texte dessous.
    tol_text = f"Votre tolérance : {fr(tol, 0)}"
    body.append(f'<line class="marker-user" x1="{_n(_x(tol))}" y1="38" x2="{_n(_x(tol))}" y2="80"/>'
                f'<text class="label-strong" x="{_n(_x(tol))}" y="112" text-anchor="{_anchor(_x(tol), tol_text)}">{escape(tol_text)}</text>')
    # Action : triangle au-dessus de la bande, texte au-dessus.
    asset_text = f"{verdict['ticker']} : risque {fr(score, 0)}"
    ax = _x(score)
    body.append(f'<path class="marker-asset" d="M{_n(ax - 7)} 24 L{_n(ax + 7)} 24 L{_n(ax)} 40 Z"/>'
                f'<text class="label-strong" x="{_n(ax)}" y="16" text-anchor="{_anchor(ax, asset_text)}">{escape(asset_text)}</text>')
    title = "Écart entre votre tolérance et le risque de l'action"
    desc = (f"Échelle de 0 à 100. Votre tolérance est à {fr(tol, 0)}, le risque de l'action à {fr(score, 0)}, "
            f"soit un écart de {fr(verdict['gap'], 0, True)} points. Vert jusqu'à {fr(g_end, 0)}, jaune jusqu'à "
            f"{fr(y_end, 0)}, rouge au-delà.")
    rows = [["Votre tolérance (effective)", fr(tol, 1)], ["Risque de l'action", fr(score, 1)],
            ["Écart", fr(verdict["gap"], 1, True)], ["Vert jusqu'à", fr(g_end, 1)], ["Jaune jusqu'à", fr(y_end, 1)]]
    return {"svg": _svg(124, title, desc, "".join(body)), "title": title,
            "table": {"headers": ["Mesure", "Valeur"], "rows": rows}}


def components_chart(verdict: dict) -> dict:
    """Une barre par mesure de risque de l'action, avec la ligne de tolérance."""
    tol = verdict["user"]["effective_tolerance"]
    drivers = sorted(verdict["drivers"], key=lambda d: ["volatility", "drawdown", "tail_risk",
                                                       "recent_stress"].index(d["key"]))
    bar_x0, bar_x1 = 230.0, 620.0
    def bx(v):
        return bar_x0 + (bar_x1 - bar_x0) * max(0.0, min(100.0, v)) / 100.0
    body = []
    row_h, top = 40, 30
    for i, d in enumerate(drivers):
        y = top + i * row_h
        over = d["excess_over_tolerance"] > 0
        cls = "bar-over" if over else "bar"
        body.append(f'<text class="label" x="8" y="{y + 15}">{escape(d["label"])}</text>'
                    f'<rect class="bar-track" x="{_n(bar_x0)}" y="{y}" width="{_n(bar_x1 - bar_x0)}" height="20" rx="4"/>'
                    f'<rect class="{cls}" x="{_n(bar_x0)}" y="{y}" width="{_n(bx(d["asset_points"]) - bar_x0)}" height="20" rx="4"/>'
                    f'<text class="value" x="{_n(bar_x1 + 10)}" y="{y + 15}">{fr(d["asset_points"], 0)} / 100'
                    f'{" ▲ dépasse" if over else ""}</text>')
    body.append(f'<line class="marker-user dashed" x1="{_n(bx(tol))}" y1="{top - 10}" x2="{_n(bx(tol))}" '
                f'y2="{top + len(drivers) * row_h - 12}"/>'
                f'<text class="label-strong" x="{_n(bx(tol))}" y="14" text-anchor="middle">Votre tolérance : {fr(tol, 0)}</text>')
    height = top + len(drivers) * row_h
    title = "Les mesures de risque de l'action face à votre tolérance"
    desc = "Quatre mesures notées de 0 à 100 ; les barres qui dépassent la ligne de votre tolérance sont marquées."
    rows = [[d["label"], fr(d["asset_points"], 1), fr(d["raw_value"], 2) + " " + d["raw_unit"].split(" ", 1)[0],
             "oui" if d["excess_over_tolerance"] > 0 else "non"] for d in drivers]
    return {"svg": _svg(height, title, desc, "".join(body)), "title": title,
            "table": {"headers": ["Mesure", "Points", "Valeur brute", "Dépasse la tolérance"], "rows": rows}}


def profile_chart(profile: dict) -> dict:
    """Poids historique / second pilier (quiz ou mises en situation), puis les indicateurs de l'historique."""
    comp = profile["components"]
    pillar = combine.second_pillar(profile)
    body = []
    bar_x0, bar_x1 = 230.0, 620.0
    def bx(v):
        return bar_x0 + (bar_x1 - bar_x0) * max(0.0, min(100.0, v)) / 100.0
    wh, wq = comp["history"]["effective_weight"], comp[pillar["key"]]["effective_weight"]
    total_w = bar_x1 - bar_x0
    body.append('<text class="label" x="8" y="19">Origine du score</text>')
    h_w = total_w * wh
    body.append(f'<rect class="seg-a" x="{_n(bar_x0)}" y="4" width="{_n(h_w)}" height="22"/>'
                f'<rect class="seg-b" x="{_n(bar_x0 + h_w)}" y="4" width="{_n(total_w - h_w)}" height="22"/>')
    if wh > 0.18:
        body.append(f'<text class="seg-text-a" x="{_n(bar_x0 + h_w / 2)}" y="19" text-anchor="middle">Opérations {fr(100 * wh, 0)} %</text>')
    if wq > 0.18:
        body.append(f'<text class="seg-text-b" x="{_n(bar_x0 + h_w + (total_w - h_w) / 2)}" y="19" text-anchor="middle">{pillar["title"]} {fr(100 * wq, 0)} %</text>')
    rows = [["Opérations passées (poids)", fr(100 * wh, 0) + " %"], [pillar["title"] + " (poids)", fr(100 * wq, 0) + " %"]]
    y = 54
    body.append('<text class="label-strong" x="8" y="46">Indicateurs de vos opérations</text>')
    for ind in profile["history"]["indicators"]:
        if ind["available"]:
            body.append(f'<text class="label" x="8" y="{y + 15}">{escape(ind["label"])}</text>'
                        f'<rect class="bar-track" x="{_n(bar_x0)}" y="{y}" width="{_n(bar_x1 - bar_x0)}" height="18" rx="4"/>'
                        f'<rect class="bar" x="{_n(bar_x0)}" y="{y}" width="{_n(bx(ind["score"]) - bar_x0)}" height="18" rx="4"/>'
                        f'<text class="value" x="{_n(bar_x1 + 10)}" y="{y + 14}">{fr(ind["score"], 0)} / 100</text>')
            rows.append([ind["label"], fr(ind["score"], 1)])
        else:
            body.append(f'<text class="label" x="8" y="{y + 15}">{escape(ind["label"])}</text>'
                        f'<text class="muted" x="{_n(bar_x0)}" y="{y + 14}">indisponible</text>')
            rows.append([ind["label"], "indisponible"])
        y += 30
    title = "Comment votre profil a été construit"
    desc = (f"Votre score vient pour {fr(100 * wh, 0)} % de vos opérations et {fr(100 * wq, 0)} % de {pillar['your']}. "
            f"Les {len(profile['history']['indicators'])} indicateurs de vos opérations sont notés de 0 à 100.")
    return {"svg": _svg(y + 4, title, desc, "".join(body)), "title": title,
            "table": {"headers": ["Élément", "Valeur"], "rows": rows}}


def universe_chart(verdict: dict, scores: dict[str, float]) -> dict:
    """Les actifs de l'univers sur l'échelle 0-100, avec l'action et la tolérance repérées."""
    tol, ticker = verdict["user"]["effective_tolerance"], verdict["ticker"]
    ordered = sorted(scores.items(), key=lambda kv: (kv[1], kv[0]))
    body = ['<line class="axis-line" x1="40" y1="92" x2="680" y2="92"/>']
    for tick in (0, 25, 50, 75, 100):
        body.append(f'<line class="tick" x1="{_n(_x(tick))}" y1="92" x2="{_n(_x(tick))}" y2="97"/>'
                    f'<text class="axis" x="{_n(_x(tick))}" y="112" text-anchor="middle">{tick}</text>')
    rows = []
    for i, (t, s) in enumerate(ordered):
        cy = 80 - (i % 3) * 13
        if t == ticker:
            continue
        body.append(f'<circle class="dot" cx="{_n(_x(s))}" cy="{cy}" r="4.5"/>')
        rows.append([t, fr(s, 1)])
    body.append(f'<line class="marker-user dashed" x1="{_n(_x(tol))}" y1="28" x2="{_n(_x(tol))}" y2="92"/>'
                f'<text class="label-strong" x="{_n(_x(tol))}" y="20" text-anchor="{_anchor(_x(tol), "Votre tolérance")}">Votre tolérance</text>')
    s = scores[ticker]
    body.append(f'<circle class="dot-selected" cx="{_n(_x(s))}" cy="86" r="8"/>'
                f'<text class="label-strong" x="{_n(_x(s))}" y="130" text-anchor="{_anchor(_x(s), ticker)}">{escape(ticker)}</text>')
    rows.insert(0, [ticker + " (cette action)", fr(s, 1)])
    title = "Où se situe cette action parmi les autres"
    desc = (f"{len(scores)} actifs placés selon leur score de risque de 0 à 100. {ticker} est à {fr(s, 0)} ; "
            f"votre tolérance est à {fr(tol, 0)}.")
    return {"svg": _svg(138, title, desc, "".join(body)), "title": title,
            "table": {"headers": ["Actif", "Score de risque"], "rows": rows}}


def price_chart(asset: AssetRiskResult) -> dict:
    """Prix normalisé (base 100) sur la fenêtre, avec la baisse maximale marquée."""
    from datetime import date
    bars = data_access.get_prices(asset.ticker, date.fromisoformat(asset.window_start),
                                  date.fromisoformat(asset.window_end))
    adj = [b.adj_close for b in bars]
    base = adj[0]
    norm = [100.0 * v / base for v in adj]
    peak_i, trough_i, worst, run_peak_i = 0, 0, 0.0, 0
    for i, v in enumerate(adj):
        if v > adj[run_peak_i]:
            run_peak_i = i
        dd = 1.0 - v / adj[run_peak_i]
        if dd > worst:
            worst, peak_i, trough_i = dd, run_peak_i, i
    x_l, x_r, y_t, y_b = 52.0, 700.0, 18.0, 188.0
    lo, hi = min(norm), max(norm)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    n = len(norm)
    def px(i): return x_l + (x_r - x_l) * i / (n - 1)
    def py(v): return y_b - (y_b - y_t) * (v - lo) / (hi - lo)
    step = max(1, n // 220)
    idx = sorted(set(list(range(0, n, step)) + [n - 1, peak_i, trough_i]))
    path = "M" + " L".join(f"{_n(px(i))} {_n(py(norm[i]))}" for i in idx)
    body = [f'<line class="axis-line" x1="{_n(x_l)}" y1="{_n(y_b)}" x2="{_n(x_r)}" y2="{_n(y_b)}"/>',
            f'<path class="price-line" d="{path}" fill="none"/>']
    for frac in (0.0, 0.5, 1.0):
        v = lo + (hi - lo) * frac
        body.append(f'<line class="grid" x1="{_n(x_l)}" y1="{_n(py(v))}" x2="{_n(x_r)}" y2="{_n(py(v))}"/>'
                    f'<text class="axis" x="{_n(x_l - 6)}" y="{_n(py(v) + 4)}" text-anchor="end">{fr(v, 0)}</text>')
    last_year = None
    for i, b in enumerate(bars):
        if b.date.year != last_year and (last_year is not None or i == 0):
            body.append(f'<text class="axis" x="{_n(px(i))}" y="{_n(y_b + 18)}" text-anchor="start">{b.date.year}</text>')
        last_year = b.date.year
    if worst > 0:
        body.append(f'<line class="drawdown" x1="{_n(px(peak_i))}" y1="{_n(py(norm[peak_i]))}" '
                    f'x2="{_n(px(trough_i))}" y2="{_n(py(norm[trough_i]))}"/>'
                    f'<circle class="dot-peak" cx="{_n(px(peak_i))}" cy="{_n(py(norm[peak_i]))}" r="5"/>'
                    f'<circle class="dot-selected" cx="{_n(px(trough_i))}" cy="{_n(py(norm[trough_i]))}" r="6"/>')
        label = f"Baisse maximale : -{fr(100 * worst, 1)} %"
        lx = px(trough_i)
        body.append(f'<text class="label-strong" x="{_n(lx)}" y="{_n(min(y_b - 6, py(norm[trough_i]) + 22))}" '
                    f'text-anchor="{_anchor(lx, label)}">{escape(label)}</text>')
    title = f"Évolution du prix de {asset.ticker} (base 100 au début)"
    desc = (f"Prix ajusté de {asset.window_start} à {asset.window_end}, ramené à 100 au départ. "
            f"Plus forte baisse entre un sommet et un creux : {fr(100 * worst, 1)} %.")
    rows = [["Début de la période", asset.window_start], ["Fin de la période", asset.window_end],
            ["Valeur finale (base 100)", fr(norm[-1], 1)], ["Plus haut", fr(max(norm), 1)],
            ["Plus bas", fr(min(norm), 1)], ["Baisse maximale", f"-{fr(100 * worst, 1)} %"]]
    return {"svg": _svg(212, title, desc, "".join(body)), "title": title,
            "table": {"headers": ["Mesure", "Valeur"], "rows": rows}}
