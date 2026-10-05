"""Command-line entry point: ``mlb-fan-pulse run --game <gamePk>``."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

from mlb_fan_pulse import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mlb-fan-pulse",
        description="Line up Reddit game-thread sentiment with MLB play-by-play and win probability.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    find = subparsers.add_parser("find-game", help="look up a gamePk from the MLB schedule")
    find.add_argument("--date", required=True, help="official game date, YYYY-MM-DD")
    find.add_argument("--home", help="home team name (partial match)")
    find.add_argument("--away", help="away team name (partial match)")
    find.set_defaults(func=cmd_find_game)

    mlb = subparsers.add_parser("mlb", help="ingest plays and win probability for one game")
    mlb.add_argument("--game", type=int, required=True, metavar="GAME_PK", help="MLB gamePk")
    mlb.set_defaults(func=cmd_mlb)

    run = subparsers.add_parser("run", help="run the full pipeline for one game")
    run.add_argument("--game", type=int, required=True, metavar="GAME_PK", help="MLB gamePk")
    run.set_defaults(func=cmd_run)

    return parser


def cmd_find_game(args: argparse.Namespace) -> int:
    from mlb_fan_pulse.ingest import mlb

    try:
        print(mlb.find_game_pk(args.date, home=args.home, away=args.away))
    except mlb.GameLookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def cmd_mlb(args: argparse.Namespace) -> int:
    from mlb_fan_pulse.ingest import mlb
    from mlb_fan_pulse.viz import charts

    tables = mlb.ingest_game(args.game)
    game = tables["games"].iloc[0]
    timeline = charts.win_prob_timeline(tables["plays"], tables["win_prob"])

    print(f"{game.away_team} @ {game.home_team}, {game.date}, {game.series_desc}")
    print(f"Final: {game.final_score}")
    print(f"{len(tables['plays'])} plays, {len(tables['win_prob'])} win probability rows\n")
    print(f"{'inn':<7}{'end (UTC)':<10}{game.home_abbr + ' WP':>7}  description")
    for row in timeline.itertuples():
        inning = f"{row.half[:3].title()} {row.inning}"
        print(f"{inning:<7}{row.end_time_utc:%H:%M:%S}  {row.home_wp_after:>6.0%}  {row.description}")

    last = tables["plays"].iloc[-1]
    if (last.home_score, last.away_score) != (game.home_score, game.away_score):
        print(
            f"\nSANITY CHECK FAILED: last play score {last.away_score}-{last.home_score} "
            f"does not match linescore {game.away_score}-{game.home_score}",
            file=sys.stderr,
        )
        return 1

    path = charts.write_html(charts.win_prob_figure(game, tables["plays"], tables["win_prob"]), f"{args.game}_win_prob.html")
    print(f"\nSanity check passed: last play score matches the linescore ({game.final_score}).")
    print(f"Win probability chart: {path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    print(f"run --game {args.game}: pipeline not implemented yet (Phase 0 skeleton).", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
