# tests/test_cli.py
from click.testing import CliRunner
from jforest.cli import main

def test_status_on_empty_db(tmp_path):
    db = str(tmp_path / "t.db")
    r = CliRunner().invoke(main, ["--db", db, "status"])
    assert r.exit_code == 0
    assert "forests" in r.output

def test_crawl_unknown_step_errors(tmp_path):
    db = str(tmp_path / "t.db")
    r = CliRunner().invoke(main, ["--db", db, "crawl", "bogus"])
    assert r.exit_code != 0

def test_reparse_unknown_step_errors(tmp_path):
    db = str(tmp_path / "t.db")
    r = CliRunner().invoke(main, ["--db", db, "reparse", "bogus"])
    assert r.exit_code != 0
