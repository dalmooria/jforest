from click.testing import CliRunner

from jforest.cli import main


def test_agent_group_exposes_ask_command(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "x.db"), "agent", "--help"])

    assert result.exit_code == 0
    assert "ask" in result.output


def test_agent_serve_command_exists(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "x.db"), "agent", "serve", "--help"])

    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output


def test_agent_eval_command_exists(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "x.db"), "agent", "eval", "--help"])

    assert result.exit_code == 0
    assert "--cases" in result.output
