from click.testing import CliRunner

from jforest.cli import main


def test_agent_group_exposes_ask_command(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "x.db"), "agent", "--help"])

    assert result.exit_code == 0
    assert "ask" in result.output
