"""Vérificateur du rapport (code, sans IA).

Un rapport est accepté seulement si : sections complètes ; chaque phrase cite au
moins un fait existant ; chaque nombre, date et sigle du texte existe dans la fiche
de faits ; aucune expression incitative ; les faits obligatoires sont cités ; la
longueur est raisonnable. Retourne la liste des erreurs (vide = accepté).
"""

from __future__ import annotations

import math
import re

from .. import config
from .facts import FactSheet

_CITATION = re.compile(r"\[F\d+(?:\s*,\s*F\d+)*\]")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER = re.compile(r"(?<![\w.,])[-+]?\d+(?:,\d+)?(?![\w])")
_SIGLE = re.compile(r"\b[A-Z]{2,6}(?:[.\-][A-Z]{1,4})?\b")


def _rounds_to(a: float, decimals: int, value: float) -> bool:
    """`value` est `a` arrondi à `decimals` décimales, au plus proche (22,5 -> 22 ou 23 : les deux usages sont acceptés)."""
    half_up = math.floor(a * 10 ** decimals + 0.5) / 10 ** decimals
    return round(a, decimals) == value or half_up == value


def _clean(text: str) -> str:
    return _CITATION.sub(" ", text)


def numbers_in(text: str) -> list[tuple[float, int]]:
    """(valeur absolue, nombre de décimales) de chaque nombre, hors dates ISO et citations."""
    text = _ISO_DATE.sub(" ", _clean(text))
    out = []
    for token in _NUMBER.findall(text):
        digits = token.lstrip("+-")
        decimals = len(digits.split(",")[1]) if "," in digits else 0
        out.append((float(digits.replace(",", ".")), decimals))
    return out


def _allowed(sheet: FactSheet, extra_facts=()) -> tuple[list[float], set[str], str]:
    values: list[float] = []
    dates: set[str] = set()
    corpus = []
    for f in list(sheet.facts) + list(extra_facts):
        for variant in (f.text, f.plain, f.expert):
            if variant:
                corpus.append(variant)
                values += [v for v, _ in numbers_in(variant)]
                dates.update(_ISO_DATE.findall(variant))
    return values, dates, " ".join(corpus)


def check_sentence(text: str, ids: list, fact_ids: dict, allowed: tuple, cited: set,
                   where: str | None, check_length: bool = False) -> list[str]:
    """Contrôle UNE phrase : faits cités existants, nombres/dates/sigles présents dans les faits,
    aucune expression incitative. Ajoute les faits cités à `cited`. Retourne les erreurs.
    Partagé par le rapport (verify_report) et les réponses de l'agent de suivi."""
    allowed_values, allowed_dates, corpus = allowed
    errors: list[str] = []
    if not text.strip():
        return [f"Phrase vide dans '{where}'."]
    if not ids:
        errors.append(f"Phrase sans fait cité : « {text[:60]} »")
    for fid in ids:
        if fid not in fact_ids:
            errors.append(f"Fait inconnu cité : {fid}.")
        else:
            cited.add(fid)
    body = _clean(text)
    for value, decimals in numbers_in(body):
        if not any(_rounds_to(a, decimals, value) for a in allowed_values):
            errors.append(f"Nombre absent des faits : {value:g} (phrase « {text[:60]} »).")
    for d in _ISO_DATE.findall(body):
        if d not in allowed_dates:
            errors.append(f"Date absente des faits : {d}.")
    for sigle in _SIGLE.findall(body):
        if sigle not in corpus and sigle not in config.REPORT_ALLOWED_TERMS:
            errors.append(f"Sigle ou titre absent des faits : {sigle}.")
    lowered = body.lower()
    for phrase in config.REPORT_BANNED_PHRASES:
        if phrase in lowered:
            errors.append(f"Expression interdite : « {phrase} ».")
    if check_length and len(body.split()) > config.REPORT_MAX_SENTENCE_WORDS:
        errors.append(f"Phrase trop longue ({len(body.split())} mots) : « {text[:60]} »")
    return errors


def verify_report(report: dict, sheet: FactSheet, check_sentence_length: bool = False,
                  check_total_length: bool = True) -> list[str]:
    errors: list[str] = []
    expected_ids = [s for s, _ in config.REPORT_SECTION_TITLES]
    sections = report.get("sections") if isinstance(report, dict) else None
    if not isinstance(sections, list):
        return ["Structure invalide : liste 'sections' absente."]
    got_ids = [s.get("id") for s in sections if isinstance(s, dict)]
    if got_ids != expected_ids:
        errors.append(f"Sections attendues {expected_ids}, reçues {got_ids}.")

    fact_ids = sheet.by_id()
    allowed = _allowed(sheet)
    cited: set[str] = set()
    all_text = []

    for section in sections:
        for sentence in section.get("sentences", []):
            text = sentence.get("text", "") if isinstance(sentence, dict) else ""
            ids = sentence.get("facts", []) if isinstance(sentence, dict) else []
            all_text.append(text)
            errors += check_sentence(text, ids, fact_ids, allowed, cited, section.get("id"),
                                     check_sentence_length)

    for fact in sheet.facts:
        if fact.must_cite and fact.min_level <= sheet.level_index() and fact.id not in cited:
            errors.append(f"Fait obligatoire non cité : {fact.id} ({fact.key}).")

    words = sum(len(_clean(t).split()) for t in all_text)
    cap = config.REPORT_MAX_WORDS[sheet.level]
    if check_total_length and words > cap:
        errors.append(f"Texte trop long : {words} mots (maximum {cap}).")
    joined = " ".join(all_text).lower()
    if sheet.final_color not in joined:
        errors.append(f"La couleur du verdict ({sheet.final_color}) n'apparaît pas dans le texte.")
    return errors
