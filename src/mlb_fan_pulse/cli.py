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

    run = subparsers.add_parser("run", help="run the full pipeline for one game")
    run.add_argument("--game", type=int, required=True, metavar="GAME_PK", help="MLB gamePk")
    run.set_defaults(func=cmd_run)

    return parser


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
