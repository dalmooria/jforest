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
