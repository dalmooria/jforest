from click.testing import CliRunner

from jforest.cli import main


def test_bench_group_exposes_report_command(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "x.db"), "bench", "--help"])

    assert result.exit_code == 0
    assert "corpus" in result.output
    assert "embeddings" in result.output
    assert "report" in result.output
