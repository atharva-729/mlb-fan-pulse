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

    reddit = subparsers.add_parser("reddit", help="find game threads and pull their comments")
    reddit.add_argument("--game", type=int, required=True, metavar="GAME_PK", help="MLB gamePk")
    reddit.set_defaults(func=cmd_reddit)

    timeline = subparsers.add_parser("timeline", help="chart comment volume against win probability")
    timeline.add_argument("--game", type=int, required=True, metavar="GAME_PK", help="MLB gamePk")
    timeline.set_defaults(func=cmd_timeline)

    sentiment = subparsers.add_parser("sentiment", help="aggregate baseline sentiment by fanbase")
    sentiment.add_argument("--game", type=int, required=True, metavar="GAME_PK", help="MLB gamePk")
    sentiment.set_defaults(func=cmd_sentiment)

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


def cmd_reddit(args: argparse.Namespace) -> int:
    import pandas as pd

    from mlb_fan_pulse import storage
    from mlb_fan_pulse.ingest import mlb, reddit
    from mlb_fan_pulse.process import clean
    from mlb_fan_pulse.viz import charts

    game = mlb.ingest_game(args.game)["games"].iloc[0]
    try:
        tables = reddit.ingest_game(game)
    except reddit.ThreadLookupError as exc:
        print(exc, file=sys.stderr)
        return 1

    threads, raw = tables["threads"], tables["comments_raw"]
    comments, dropped = clean.clean_comments(raw)
    storage.write_table("comments", args.game, comments)

    print(f"{game.away_team} @ {game.home_team}, {game.date}\n")
    for thread in threads.itertuples():
        fetched = int((raw["thread_id"] == thread.thread_id).sum())
        kept = int((comments["thread_id"] == thread.thread_id).sum())
        print(f"r/{thread.subreddit} {thread.thread_type} thread {thread.thread_id}: {thread.title}")
        print(f"  Reddit count {thread.num_comments}, fetched {fetched}, kept after cleaning {kept}")
    print("\nDropped: " + ", ".join(f"{reason} {count}" for reason, count in dropped.items()))

    game_thread_ids = threads.loc[threads["thread_type"] == "game", "thread_id"]
    game_comments = comments[comments["thread_id"].isin(game_thread_ids)]
    per_minute = charts.comments_per_minute(game_comments)
    print(
        f"\nGame thread: {len(game_comments)} comments from {game_comments['created_utc'].min():%H:%M} "
        f"to {game_comments['created_utc'].max():%m-%d %H:%M} UTC, "
        f"peak {per_minute.max()} per minute at {per_minute.idxmax():%H:%M} UTC"
    )

    print("\n20 random comments from the game thread:")
    for row in game_comments.sample(n=min(20, len(game_comments)), random_state=0).sort_values("created_utc").itertuples():
        flair = "no flair" if pd.isna(row.author_flair_text) else row.author_flair_text
        body = " ".join(row.body.split())
        print(f"  [{row.created_utc:%H:%M:%S}] ({flair}) {body[:160]}")

    path = charts.write_html(
        charts.comment_volume_figure(game, game_comments, " (game thread)"), f"{args.game}_comment_volume.html"
    )
    print(f"\nComments-per-minute chart: {path}")
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    from mlb_fan_pulse import storage
    from mlb_fan_pulse.viz import charts

    try:
        tables = {name: storage.read_table(name, args.game) for name in ("games", "plays", "win_prob", "threads", "comments")}
    except FileNotFoundError as exc:
        print(f"missing table ({exc.filename}); run `mlb` and `reddit` for this game first", file=sys.stderr)
        return 1

    game, plays, win_prob = tables["games"].iloc[0], tables["plays"], tables["win_prob"]
    game_thread_ids = tables["threads"].loc[tables["threads"]["thread_type"] == "game", "thread_id"]
    comments = tables["comments"][tables["comments"]["thread_id"].isin(game_thread_ids)]

    timeline = charts.reaction_table(charts.win_prob_timeline(plays, win_prob), comments)
    marked = charts.key_plays(timeline)
    in_game = comments[
        (comments["created_utc"] >= plays["start_time_utc"].min()) & (comments["created_utc"] <= plays["end_time_utc"].max())
    ]
    typical = charts.comments_per_minute(in_game).median()

    print(f"{game.away_team} @ {game.home_team}, {game.date} ({game.final_score})")
    print(f"Typical in-game volume: {typical:.0f} comments per minute (median)\n")
    print(f"Key plays, with comments per minute in the {charts.REACTION_MINUTES} minutes after each:")
    print(f"{'end (UTC)':<10}{'inn':<7}{'WP chg':>7}{'c/min':>7}{'x typ':>7}  play")
    for row in marked.itertuples():
        inning = f"{row.half[:3].title()} {row.inning}"
        print(
            f"{row.end_time_utc:%H:%M:%S}  {inning:<7}{row.wp_delta:>+7.0%}{row.reaction_per_min:>7.0f}"
            f"{row.reaction_per_min / typical:>6.1f}x  {row.event}: {row.batter_name}"
        )

    other = timeline.drop(marked.index)
    print(
        f"\nMedian reaction: key plays {marked['reaction_per_min'].median():.0f} per minute, "
        f"all other plays {other['reaction_per_min'].median():.0f} per minute"
    )

    path = charts.write_html(
        charts.volume_vs_win_prob_figure(game, plays, win_prob, comments), f"{args.game}_volume_vs_win_prob.html"
    )
    print(f"Chart: {path}")
    return 0


def cmd_sentiment(args: argparse.Namespace) -> int:
    from mlb_fan_pulse import storage
    from mlb_fan_pulse.process import sentiment
    from mlb_fan_pulse.viz import charts

    try:
        tables = {name: storage.read_table(name, args.game) for name in ("games", "plays", "win_prob", "threads", "comments")}
    except FileNotFoundError as exc:
        print(f"missing table ({exc.filename}); run `mlb` and `reddit` for this game first", file=sys.stderr)
        return 1
    scores_path = storage.table_path("comment_scores", args.game)
    if not scores_path.exists():
        print(
            f"no baseline scores at {scores_path}\n"
            f"Run notebooks/baseline_sentiment_colab.ipynb on Google Colab with "
            f"{storage.table_path('comments', args.game)}, then save its download to that path.",
            file=sys.stderr,
        )
        return 1

    game, plays, win_prob = tables["games"].iloc[0], tables["plays"], tables["win_prob"]
    game_thread_ids = tables["threads"].loc[tables["threads"]["thread_type"] == "game", "thread_id"]
    comments = tables["comments"][tables["comments"]["thread_id"].isin(game_thread_ids)]
    scored = comments.merge(storage.read_table("comment_scores", args.game), on="comment_id", how="inner")
    if len(scored) < len(comments):
        print(f"warning: {len(comments) - len(scored)} of {len(comments)} comments have no score", file=sys.stderr)
    scored = sentiment.with_fanbase(scored, game)

    halves = sentiment.half_innings(plays)
    tagged = sentiment.assign_half_inning(scored, halves)
    per_half = sentiment.by_half_inning(tagged, halves)
    storage.write_table("sentiment_half_inning", args.game, per_half)
    storage.write_table("sentiment_minute", args.game, sentiment.by_minute(tagged))

    names = {"home": game.home_name, "away": game.away_name, "other": "other teams", "none": "no flair"}
    print(f"{game.away_team} @ {game.home_team}, {game.date} ({game.final_score})")
    print(f"{len(scored)} scored game-thread comments, {len(tagged)} during the game\n")
    print("In-game comments and mean sentiment by fanbase:")
    for side, group in tagged.groupby("fanbase"):
        print(f"  {names[side]:<12}{len(group):>6}  {group['base_sentiment'].mean():+.2f}")

    wide = per_half.pivot(index="half_inning", columns="fanbase", values="sentiment").reindex(halves["half_inning"])
    print(f"\nMean sentiment by half-inning:\n{'':<6}{game.home_name + ' fans':>14}{game.away_name + ' fans':>14}")
    for half_inning, row in wide.iterrows():
        print(f"{half_inning:<6}{row.get('home', float('nan')):>+14.2f}{row.get('away', float('nan')):>+14.2f}")

    reactions = sentiment.scoring_reactions(scored, plays)
    print("\nGut check, sentiment change in the 3 minutes after each scoring play vs. the 3 before:")
    passed = 0
    for row in reactions.itertuples():
        other_side = "home" if row.scoring_side == "away" else "away"
        scoring_change = getattr(row, f"{row.scoring_side}_after") - getattr(row, f"{row.scoring_side}_before")
        other_change = getattr(row, f"{other_side}_after") - getattr(row, f"{other_side}_before")
        ok = scoring_change > 0 > other_change
        passed += ok
        print(
            f"  {row.half_inning} {row.end_time_utc:%H:%M} {names[row.scoring_side]} score: "
            f"{names[row.scoring_side]} fans {scoring_change:+.2f} (n={getattr(row, f'{row.scoring_side}_n_after')}), "
            f"{names[other_side]} fans {other_change:+.2f} (n={getattr(row, f'{other_side}_n_after')})"
            f"  {'as expected' if ok else 'NOT as expected'}"
        )
    print(f"  {passed} of {len(reactions)} scoring plays moved both fanbases the expected way")

    path = charts.write_html(
        charts.sentiment_by_fanbase_figure(game, plays, win_prob, per_half), f"{args.game}_sentiment_by_fanbase.html"
    )
    print(f"\nChart: {path}")
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
