# tests/test_parser_policies.py
from pathlib import Path
from jforest.parsers.policies import (
    parse_policy_all,
    parse_policy_detail,
    parse_policy_detail_menus,
    parse_policy_detail_title,
    policy_detail_title_or_default,
)

FX = Path(__file__).parent / "fixtures"

def test_parse_policy_all_returns_rows_anchored_on_name():
    rows = parse_policy_all((FX / "policy_all.html").read_text(encoding="utf-8"))
    assert len(rows) >= 50
    sample = rows[0]
    assert set(sample) >= {"name", "operates_rooms", "operates_campsite",
                           "operates_waitlist", "fcfs_method", "lottery_types", "priority_types"}
    assert "휴양림" in (sample["name"] or "")
    assert sample["operates_rooms"] in (0, 1)
    # 최소 한 곳은 객실 운영(1)
    assert any(r["operates_rooms"] == 1 for r in rows)

def test_parse_policy_all_has_known_forest_name():
    rows = parse_policy_all((FX / "policy_all.html").read_text(encoding="utf-8"))
    names = " ".join(r["name"] for r in rows if r["name"])
    assert "가리왕산" in names or "유명산" in names

def test_parse_policy_detail_returns_text():
    txt = parse_policy_detail((FX / "policy_detail.html").read_text(encoding="utf-8"))
    assert txt and len(txt) > 20
    assert "선착순" in txt or "예약" in txt


def test_parse_policy_detail_menus_returns_rule_links():
    body = (FX / "policy_detail.html").read_text(encoding="utf-8")
    menus = parse_policy_detail_menus(body)
    assert any(m["rule_id"] == "101" for m in menus)
    assert all(m["menu_id"] for m in menus)
    assert parse_policy_detail_title(body)


def test_policy_detail_title_falls_back_to_rule_id():
    assert policy_detail_title_or_default("101", None) == "선착순 예약정책"
    assert policy_detail_title_or_default("111", "") == "월추첨제 예약정책"
