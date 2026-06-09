from jforest.bench import expected_hit_rank, mrr_at_k, recall_at_k


def test_expected_hit_rank_matches_source_table_and_pk():
    expected = [{"source_table": "notices", "source_pk": "F1:N1"}]
    results = [
        {"source_table": "forests", "source_pk": "F1"},
        {"source_table": "notices", "source_pk": "F1:N1"},
    ]

    assert expected_hit_rank(expected, results, k=10) == 2


def test_recall_and_mrr_at_k():
    assert recall_at_k(2, k=5) == 1.0
    assert recall_at_k(None, k=5) == 0.0
    assert mrr_at_k(2, k=5) == 0.5
    assert mrr_at_k(None, k=5) == 0.0
