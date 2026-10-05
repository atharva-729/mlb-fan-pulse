import pytest

from mlb_fan_pulse import cli


def test_help_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])

    assert exc.value.code == 0
    assert "run" in capsys.readouterr().out


def test_run_requires_game():
    with pytest.raises(SystemExit) as exc:
        cli.main(["run"])

    assert exc.value.code == 2


def test_run_parses_game_pk():
    args = cli.build_parser().parse_args(["run", "--game", "12345"])

    assert args.game == 12345
    assert args.func is cli.cmd_run
