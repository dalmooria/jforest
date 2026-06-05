from jforest.answer_eval import (
    AnswerEvaluation,
    EvalCase,
    build_judge_messages,
    evaluate_answer,
    parse_judge_response,
    run_answer_eval,
    summarize_answer_eval,
)
from jforest.rag import RagAnswer, RetrievedDocument


def _doc(text="평일 30% 할인", instt_name="산삼자연휴양림"):
    return RetrievedDocument(
        doc_id="discount:679",
        source_table="discount_policies",
        source_pk="679",
        doc_type="discount",
        title_or_name="장애인(등급 : 1급 ~ 6급)",
        text=text,
        score=0.67,
        instt_id="ID02030048",
        instt_name=instt_name,
    )


def test_build_judge_messages_contains_question_answer_evidence_and_json_rule():
    messages = build_judge_messages(
        question="장애인 할인 되는 곳",
        answer="산삼자연휴양림 30% 할인 [1]",
        evidence="[1] 산삼자연휴양림 평일 30% 할인",
    )

    assert messages[0]["role"] == "system"
    assert "faithfulness" in messages[0]["content"]
    assert "answer_relevance" in messages[0]["content"]
    assert "JSON" in messages[0]["content"]
    user = messages[1]["content"]
    assert "장애인 할인 되는 곳" in user
    assert "산삼자연휴양림 30% 할인 [1]" in user
    assert "산삼자연휴양림 평일 30% 할인" in user


def test_parse_judge_response_handles_plain_and_fenced_json_and_clamps():
    plain = parse_judge_response('{"faithfulness": 0.9, "answer_relevance": 0.8, "notes": "ok"}')
    assert plain["faithfulness"] == 0.9
    assert plain["answer_relevance"] == 0.8
    assert plain["notes"] == "ok"

    fenced = parse_judge_response('```json\n{"faithfulness": 1.5, "answer_relevance": -0.2}\n```')
    assert fenced["faithfulness"] == 1.0  # clamped to [0,1]
    assert fenced["answer_relevance"] == 0.0


class FakeJudge:
    def __init__(self, faithfulness=0.9, answer_relevance=0.8):
        self.faithfulness = faithfulness
        self.answer_relevance = answer_relevance
        self.seen = None

    def score(self, question, answer, evidence):
        self.seen = (question, answer, evidence)
        return {
            "faithfulness": self.faithfulness,
            "answer_relevance": self.answer_relevance,
            "notes": "fake",
        }


def test_evaluate_answer_uses_judge_and_flags_insufficient():
    judge = FakeJudge(faithfulness=0.95, answer_relevance=0.7)
    rag = RagAnswer(
        question="장애인 할인 되는 곳",
        answer="산삼자연휴양림 30% 할인 [1]",
        evidence=[_doc()],
        model="gpt-4.1-mini",
        candidate="openai-large",
    )

    result = evaluate_answer(EvalCase(id="q1", question=rag.question), rag, judge)

    assert isinstance(result, AnswerEvaluation)
    assert result.case_id == "q1"
    assert result.faithfulness == 0.95
    assert result.answer_relevance == 0.7
    assert result.insufficient is False
    # judge saw the rendered evidence (forest name surfaced)
    assert "산삼자연휴양림" in judge.seen[2]


def test_evaluate_answer_marks_insufficient_when_no_evidence_found():
    judge = FakeJudge()
    rag = RagAnswer(
        question="없는 조건",
        answer="검색된 근거가 충분하지 않습니다.",
        evidence=[],
        model="gpt-4.1-mini",
        candidate="openai-large",
    )

    result = evaluate_answer(EvalCase(id="q2", question=rag.question), rag, judge)

    assert result.insufficient is True


def test_run_answer_eval_orchestrates_answer_fn_then_judge():
    cases = [EvalCase(id="q1", question="장애인 할인"), EvalCase(id="q2", question="다자녀 혜택")]

    def fake_answer_fn(question, **kwargs):
        return RagAnswer(
            question=question,
            answer=f"{question} 답변 [1]",
            evidence=[_doc()],
            model="gpt-4.1-mini",
            candidate="openai-large",
        )

    results = run_answer_eval(cases, answer_fn=fake_answer_fn, judge=FakeJudge())

    assert [r.case_id for r in results] == ["q1", "q2"]
    assert results[0].answer == "장애인 할인 답변 [1]"


def test_summarize_answer_eval_averages_metrics():
    evals = [
        AnswerEvaluation("q1", "장애인 할인", "a", 0.9, 0.8, False, "x"),
        AnswerEvaluation("q2", "다자녀", "b", 0.7, 0.6, True, "y"),
    ]

    summary = summarize_answer_eval(evals)

    assert summary["count"] == 2
    assert summary["faithfulness"] == 0.8
    assert round(summary["answer_relevance"], 3) == 0.7
    assert summary["insufficient_rate"] == 0.5


def test_load_eval_cases_reads_jsonl(tmp_path):
    from jforest.answer_eval import load_eval_cases

    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id":"a","question":"장애인 할인","category":"policy"}\n'
        '{"id":"b","question":"바베큐 객실"}\n',
        encoding="utf-8",
    )

    cases = load_eval_cases(str(path))

    assert [c.id for c in cases] == ["a", "b"]
    assert cases[0].category == "policy"
    assert cases[1].category is None
