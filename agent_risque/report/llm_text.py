"""Reformulation du rapport par un modèle (Amazon Bedrock), encadrée par le vérificateur.

Le modèle ne reçoit QUE la fiche de faits (aucun nom, aucun compte : profils fictifs)
et ne calcule rien. Sa sortie est acceptée seulement si verify.verify_report ne
trouve aucune erreur ; sinon un nouvel essai avec la liste des erreurs, puis échec
(l'appelant retombe sur le texte fixe). 'temperature' est déprécié sur ces modèles :
le résultat accepté est mis en cache pour que la même entrée redonne le même rapport.
Aucun raisonnement interne du modèle n'est lu ni conservé : seul le JSON final l'est.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .. import config
from .facts import FactSheet
from .verify import verify_report


class ReportGenerationError(RuntimeError):
    """La reformulation n'a pas abouti (le texte fixe prend le relais)."""


LEVEL_GUIDE = {
    "debutant": "mots simples, aucun jargon, une idée par phrase",
    "intermediaire": "langage clair ; explique chaque terme technique en une phrase",
    "avance": "termes financiers précis permis ; garde tous les chiffres utiles",
}

SYSTEM_PROMPT = """Tu rédiges un court rapport en français pour un investisseur fictif, dans un exercice de simulation.
Tu reçois une liste de FAITS numérotés. Règles absolues :
1. N'écris rien qui ne soit pas dans les faits : aucun chiffre, date, nom, sigle ou titre boursier absent des faits.
2. Reprends les nombres tels quels (même précision) ; n'en calcule aucun.
3. Chaque phrase cite les identifiants des faits qu'elle utilise, dans la liste "facts" de la phrase.
4. Cite obligatoirement tous les faits marqués "obligatoire".
5. Ne donne aucun conseil : n'écris jamais d'ordre ou de recommandation d'acheter ou de vendre ; décris l'adéquation avec le profil.
6. Phrases de 25 mots au plus. Mentionne la couleur du verdict en toutes lettres.
7. N'explique pas ton raisonnement. Réponds uniquement par un objet JSON, sans texte autour.
Format : {"sections": [{"id": "<id de section>", "sentences": [{"text": "...", "facts": ["F1"]}]}]}
Sections, dans cet ordre : %s.""" % ", ".join(s for s, _ in config.REPORT_SECTION_TITLES)


def _facts_payload(sheet: FactSheet) -> dict:
    selected = sheet.selected()
    return {
        "niveau": sheet.level,
        "consigne_de_niveau": LEVEL_GUIDE[sheet.level],
        "couleur_du_verdict": sheet.final_color,
        "longueur_maximale_en_mots": config.REPORT_MAX_WORDS[sheet.level],
        "sections": {
            section_id: [
                {"id": f.id, "type": f.type, "obligatoire": f.must_cite, "texte": f.text_for(sheet.level)}
                for f in selected[section_id]
            ]
            for section_id, _ in config.REPORT_SECTION_TITLES
        },
    }


def cache_key(sheet: FactSheet, model_id: str) -> str:
    payload = json.dumps({"facts": _facts_payload(sheet), "model": model_id,
                          "prompt": config.REPORT_PROMPT_VERSION, "system": SYSTEM_PROMPT},
                         sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_bedrock_client():
    try:
        import boto3
    except ImportError as exc:
        raise ReportGenerationError("boto3 n'est pas installé.") from exc
    return boto3.client("bedrock-runtime", region_name=config.REPORT_REGION)


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("aucun objet JSON dans la réponse")
    return json.loads(match.group(0))


def _normalise(parsed: dict) -> dict:
    by_id = {s.get("id"): s for s in parsed.get("sections", []) if isinstance(s, dict)}
    sections = []
    for section_id, title in config.REPORT_SECTION_TITLES:
        raw = by_id.get(section_id, {})
        sentences = []
        for s in raw.get("sentences", []):
            if isinstance(s, dict):
                sentences.append({"text": str(s.get("text", "")).strip(),
                                  "facts": [str(i) for i in s.get("facts", [])]})
        sections.append({"id": section_id, "title": title, "sentences": sentences})
    return {"sections": sections}


def generate_verified(sheet: FactSheet, client=None, model_id: str | None = None,
                      cache_dir: Path | None = None, use_cache: bool = True) -> tuple[dict, dict]:
    """Retourne (rapport vérifié, méta). Lève ReportGenerationError si aucun essai n'est accepté."""
    model_id = model_id or config.REPORT_MODEL_ID
    cache_dir = Path(cache_dir) if cache_dir else config.REPORT_CACHE_DIR
    key = cache_key(sheet, model_id)
    cache_file = cache_dir / f"{key}.json"

    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if not verify_report(cached["report"], sheet, check_sentence_length=True):
            return cached["report"], {"mode": "llm", "model_id": model_id, "attempts": 0, "cache_hit": True,
                                      "fallback_reason": None}

    client = client or make_bedrock_client()
    errors: list[str] = []
    for attempt in range(1, config.REPORT_MAX_ATTEMPTS + 1):
        user_text = json.dumps(_facts_payload(sheet), ensure_ascii=False, indent=1)
        if errors:
            user_text += "\n\nTa réponse précédente a été refusée pour ces raisons, corrige-les :\n- " + "\n- ".join(errors[:12])
        try:
            response = client.converse(
                modelId=model_id,
                system=[{"text": SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": user_text}]}],
                inferenceConfig={"maxTokens": config.REPORT_MAX_TOKENS},
            )
            text = "".join(part.get("text", "") for part in response["output"]["message"]["content"])
            report = _normalise(_parse_json(text))
        except Exception as exc:                                   # réseau, droits, JSON invalide...
            errors = [f"appel ou analyse impossible : {type(exc).__name__}: {exc}"]
            continue
        errors = verify_report(report, sheet, check_sentence_length=True)
        if not errors:
            if use_cache:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"report": report, "model_id": model_id}, ensure_ascii=False,
                                                 sort_keys=True, indent=1), encoding="utf-8")
            return report, {"mode": "llm", "model_id": model_id, "attempts": attempt, "cache_hit": False,
                            "fallback_reason": None}
    raise ReportGenerationError("; ".join(errors[:5]) or "échec de la reformulation")
