from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Protocol

from jforest.rag import RagAnswer, answer_question, format_evidence

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    category: str | None = None


@dataclass(frozen=True)
class AnswerEvaluation:
    case_id: str
    question: str
    answer: str
    faithfulness: float
    answer_relevance: float
    insufficient: bool
    notes: str


class Judge(Protocol):
    def score(self, question: str, answer: str, evidence: str) -> dict:
        ...


def _clamp(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def build_judge_messages(question: str, answer: str, evidence: str) -> list[dict[str, str]]:
    system = (
        "너는 RAG 답변 채점관이다. 질문, 모델 답변, 검색된 근거를 보고 두 지표를 0~1로 채점한다. "
        "faithfulness: 답변의 모든 주장이 근거 안에서 뒷받침되는 정도(근거에 없는 내용을 지어내면 낮음). "
        "answer_relevance: 답변이 질문에 실제로 답하는 정도. "
        "반드시 JSON만 출력한다. 형식: "
        '{"faithfulness": <0~1>, "answer_relevance": <0~1>, "notes": "<한 줄 근거>"}'
    )
    user = f"질문:\n{question}\n\n모델 답변:\n{answer}\n\n검색된 근거:\n{evidence}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_judge_response(text: str) -> dict:
    match = _FENCE.search(text)
    payload = match.group(1) if match else text
    data = json.loads(payload)
    return {
        "faithfulness": _clamp(data.get("faithfulness")),
        "answer_relevance": _clamp(data.get("answer_relevance")),
        "notes": str(data.get("notes") or ""),
    }


class OpenAIJudge:
    def __init__(self, model: str = "gpt-4.1-mini"):
        from openai import OpenAI

        self.model = model
        self.client = OpenAI(timeout=120.0)

    def score(self, question: str, answer: str, evidence: str) -> dict:
        messages = build_judge_messages(question, answer, evidence)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return parse_judge_response(response.choices[0].message.content or "{}")


def load_eval_cases(path: str) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cases.append(
                EvalCase(id=row["id"], question=row["question"], category=row.get("category"))
            )
    return cases


def evaluate_answer(case: EvalCase, rag: RagAnswer, judge: Judge) -> AnswerEvaluation:
    evidence = format_evidence(rag.evidence)
    scored = judge.score(case.question, rag.answer, evidence)
    return AnswerEvaluation(
        case_id=case.id,
        question=case.question,
        answer=rag.answer,
        faithfulness=scored["faithfulness"],
        answer_relevance=scored["answer_relevance"],
        insufficient=not rag.evidence,
        notes=scored.get("notes", ""),
    )


def run_answer_eval(
    cases: list[EvalCase],
    *,
    answer_fn: Callable[..., RagAnswer] = answer_question,
    judge: Judge | None = None,
    **answer_kwargs,
) -> list[AnswerEvaluation]:
    judge = judge or OpenAIJudge()
    results: list[AnswerEvaluation] = []
    for case in cases:
        rag = answer_fn(case.question, **answer_kwargs)
        results.append(evaluate_answer(case, rag, judge))
    return results


def summarize_answer_eval(evals: list[AnswerEvaluation]) -> dict:
    if not evals:
        return {
            "count": 0,
            "faithfulness": 0.0,
            "answer_relevance": 0.0,
            "insufficient_rate": 0.0,
        }
    n = len(evals)
    return {
        "count": n,
        "faithfulness": sum(e.faithfulness for e in evals) / n,
        "answer_relevance": sum(e.answer_relevance for e in evals) / n,
        "insufficient_rate": sum(1 for e in evals if e.insufficient) / n,
    }
