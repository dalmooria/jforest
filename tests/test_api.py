from fastapi.testclient import TestClient

from jforest.api import create_app
from jforest.rag import RagAnswer, RetrievedDocument


def _fake_answer(question, **kwargs):
    return RagAnswer(
        question=question,
        answer="산삼자연휴양림에서 30% 할인이 적용됩니다. [1]",
        evidence=[
            RetrievedDocument(
                doc_id="discount:679",
                source_table="discount_policies",
                source_pk="679",
                doc_type="discount",
                title_or_name="장애인(등급 : 1급 ~ 6급)",
                text="평일 30% 할인",
                score=0.673,
                instt_id="ID02030048",
                instt_name="산삼자연휴양림",
            )
        ],
        model="gpt-4.1-mini",
        candidate="openai-large",
    )


def test_ask_returns_answer_and_evidence_json():
    client = TestClient(create_app(answer_fn=_fake_answer))

    resp = client.post("/ask", json={"question": "장애인 할인 되는 곳"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "산삼자연휴양림에서 30% 할인이 적용됩니다. [1]"
    assert body["candidate"] == "openai-large"
    assert body["model"] == "gpt-4.1-mini"
    assert body["evidence"][0]["instt_name"] == "산삼자연휴양림"
    assert body["evidence"][0]["source_table"] == "discount_policies"


def test_ask_passes_question_and_options_to_answer_fn():
    captured = {}

    def capturing_answer(question, **kwargs):
        captured["question"] = question
        captured["kwargs"] = kwargs
        return _fake_answer(question, **kwargs)

    client = TestClient(create_app(answer_fn=capturing_answer))

    client.post("/ask", json={"question": "다자녀 혜택", "limit": 5, "candidate": "openai-large"})

    assert captured["question"] == "다자녀 혜택"
    assert captured["kwargs"]["limit"] == 5
    assert captured["kwargs"]["candidate_name"] == "openai-large"


def test_ask_rejects_empty_question():
    client = TestClient(create_app(answer_fn=_fake_answer))

    resp = client.post("/ask", json={"question": "   "})

    assert resp.status_code == 422


def test_index_serves_chat_html():
    client = TestClient(create_app(answer_fn=_fake_answer))

    resp = client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text.lower()
    assert "/ask" in resp.text
