"""Quiz de 5 mises en situation. Barème fixe (config.QUIZ_QUESTIONS), aucun hasard.

Les réponses sont des indices (0 à 3) dans l'ordre des réponses de la question.
Score du quiz = moyenne des points des questions répondues.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import config


@dataclass
class QuizResult:
    score: float | None            # 0-100, None si aucune réponse
    n_answered: int
    n_questions: int
    items: list[dict] = field(default_factory=list)   # contribution de chaque question
    warnings: list[str] = field(default_factory=list)


def get_questions() -> list[dict]:
    """Questions et réponses à afficher (sans les points)."""
    return [
        {"id": q["id"], "text": q["text"], "answers": [text for text, _ in q["answers"]]}
        for q in config.QUIZ_QUESTIONS
    ]


def score_quiz(answers: dict[str, int]) -> QuizResult:
    questions = config.QUIZ_QUESTIONS
    warnings: list[str] = []
    known = {q["id"] for q in questions}
    for qid in sorted(set(answers) - known):
        warnings.append(f"Réponse ignorée : question inconnue '{qid}'.")

    picked: list[tuple[dict, int, float]] = []
    for q in questions:
        if q["id"] not in answers:
            warnings.append(f"Question '{q['id']}' sans réponse.")
            continue
        idx = answers[q["id"]]
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(q["answers"]):
            warnings.append(f"Réponse invalide pour '{q['id']}' : {idx!r}.")
            continue
        picked.append((q, idx, q["answers"][idx][1]))

    n = len(picked)
    if n == 0:
        return QuizResult(None, 0, len(questions), [], warnings)
    score = math.fsum(points for _, _, points in picked) / n
    items = [
        {"question_id": q["id"], "answer_index": idx, "points": points, "contribution": points / n}
        for q, idx, points in picked
    ]
    return QuizResult(score, n, len(questions), items, warnings)
