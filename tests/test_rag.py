from jforest.rag import RetrievedDocument, build_messages, format_evidence


def test_format_evidence_includes_source_identity_and_text():
    docs = [
        RetrievedDocument(
            doc_id="discount:1",
            source_table="discount_policies",
            source_pk="1",
            doc_type="discount",
            title_or_name="장애인",
            text="장애인 대상 객실 할인 50%",
            score=0.91,
            instt_id="F001",
            goods_id=None,
        )
    ]

    evidence = format_evidence(docs)

    assert "[1]" in evidence
    assert "discount_policies:1" in evidence
    assert "장애인 대상 객실 할인 50%" in evidence
    assert "score=0.910" in evidence


def test_build_messages_requires_evidence_bound_answer():
    messages = build_messages(
        question="장애인 할인 되는 곳 알려줘",
        evidence="discount_policies:1\n장애인 대상 객실 할인 50%",
    )

    assert messages[0]["role"] == "system"
    assert "검색된 근거" in messages[0]["content"]
    assert "충분하지 않으면" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "장애인 할인 되는 곳 알려줘" in messages[1]["content"]


def test_empty_evidence_is_explicit():
    evidence = format_evidence([])
    messages = build_messages("없는 조건 알려줘", evidence)

    assert evidence == "검색된 근거가 없습니다."
    assert "검색된 근거가 없습니다." in messages[1]["content"]


from jforest.embeddings import EmbeddingCandidate
from jforest.rag import answer_question


class FakeEmbedder:
    candidate = EmbeddingCandidate("fake", 3, "test", "fake-model")

    def embed_texts(self, texts):
        assert texts == ["바베큐 하기 좋은 곳"]
        return [[0.1, 0.2, 0.3]]


class FakeIndex:
    def search(self, vector, limit):
        assert vector == [0.1, 0.2, 0.3]
        assert limit == 8
        return [
            {
                "doc_id": "room_usage:R1",
                "source_table": "room_usage_texts",
                "source_pk": "R1",
                "doc_type": "room_usage",
                "title_or_name": "숲속의집",
                "text": "바베큐 시설 이용 가능",
                "score": 0.88,
                "instt_id": "F001",
                "goods_id": "R1",
            }
        ]


class FakeGenerator:
    model = "fake-chat"

    def generate(self, messages):
        assert "바베큐 하기 좋은 곳" in messages[1]["content"]
        assert "바베큐 시설 이용 가능" in messages[1]["content"]
        return "숲속의집은 바베큐 시설 이용 가능 근거가 있습니다. [1]"


def test_answer_question_uses_retrieval_and_generation():
    result = answer_question(
        "바베큐 하기 좋은 곳",
        embedder=FakeEmbedder(),
        index=FakeIndex(),
        generator=FakeGenerator(),
    )

    assert result.answer == "숲속의집은 바베큐 시설 이용 가능 근거가 있습니다. [1]"
    assert result.candidate == "fake"
    assert result.model == "fake-chat"
    assert result.evidence[0].source_table == "room_usage_texts"


def test_format_evidence_shows_forest_name_when_present():
    docs = [
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
    ]

    evidence = format_evidence(docs)

    assert "산삼자연휴양림" in evidence
    assert "discount_policies:679" in evidence


class FakeNameResolver:
    def resolve(self, instt_ids):
        assert instt_ids == ["F001"]
        return {"F001": "테스트자연휴양림"}


def test_answer_question_enriches_forest_name():
    result = answer_question(
        "바베큐 하기 좋은 곳",
        embedder=FakeEmbedder(),
        index=FakeIndex(),
        generator=FakeGenerator(),
        name_resolver=FakeNameResolver(),
    )

    assert result.evidence[0].instt_name == "테스트자연휴양림"
