"""Trace d'exécution : les étapes, les données et les versions derrière un rapport."""

from __future__ import annotations

from .. import combine, config
from ..asset_score import AssetRiskResult


def build_trace(verdict: dict, profile: dict, asset: AssetRiskResult, meta: dict, level: str) -> list[dict]:
    prices = next((s for s in asset.data_sources if s["file"] == "prices_daily.csv"), {})
    steps = [
        {"step": "Lecture des données", "module": "data_access.py",
         "detail": f"prices_daily.csv ({prices.get('source', 'source inconnue')}, extraction du "
                   f"{prices.get('retrieved_on', 'date inconnue')}), assets_universe.csv, fx_usdcad_daily.csv."},
        {"step": "Score de votre profil",
         "module": ("history_v2.py, situations.py, combine.py" if profile.get("model", {}).get("version") == "v2"
                    else "history_score.py, quiz.py, combine.py"),
         "detail": f"{profile['history']['n_valid_trades']} opérations valides, {profile[combine.second_pillar(profile)['key']]['n_answered']} "
                   f"{'réponses aux mises en situation' if profile.get('model', {}).get('version') == 'v2' else 'réponses au quiz'} ; "
                   f"score {profile['final_score_display']} sur 100, confiance {profile['confidence']['label']}."},
        {"step": "Score de l'action", "module": "asset_score.py",
         "detail": f"{asset.ticker} du {asset.window_start} au {asset.window_end} ({asset.n_returns} variations journalières) ; "
                   f"score {asset.score_display} sur 100, confiance {asset.confidence['label']}."},
        {"step": "Comparaison", "module": "comparison.py",
         "detail": f"écart {verdict['gap']:+.1f} point(s), couleur du risque {verdict['risk_color']}, "
                   f"seuils {verdict['thresholds']['green_max_gap']:g} et {verdict['thresholds']['yellow_max_gap']:g}."},
        {"step": "Contraintes", "module": "constraints.py",
         "detail": "; ".join(f"{c['key']} : {c['status']}" for c in verdict["constraints"]) + f" ; couleur finale {verdict['final_color']}."},
    ]
    if meta["mode"] == "llm":
        text = f"reformulation par {meta['model_id']} ({'cache' if meta['cache_hit'] else str(meta['attempts']) + ' essai(s)'}), vérifiée."
    else:
        text = "texte fixe sans intelligence artificielle" + (
            f" (repli : {meta['fallback_reason']})" if meta.get("fallback_reason") else "") + "."
    steps.append({"step": "Rédaction du rapport", "module": "report/",
                  "detail": f"niveau {level} ; {text} Version de la configuration {config.CONFIG_VERSION}, "
                            f"empreinte {config.fingerprint()}."})
    return steps
