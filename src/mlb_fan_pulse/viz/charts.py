"""Plotly figures, exported as standalone HTML."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from mlb_fan_pulse import config


def reports_dir() -> Path:
    return config.PROJECT_ROOT / "reports"


def win_prob_timeline(plays: pd.DataFrame, win_prob: pd.DataFrame) -> pd.DataFrame:
    """Plays joined to win probability on ``at_bat_index``, in game order."""
    return plays.merge(win_prob, on=["game_pk", "at_bat_index"], how="inner").sort_values("at_bat_index")


def win_prob_figure(game: pd.Series, plays: pd.DataFrame, win_prob: pd.DataFrame) -> go.Figure:
    """Home win probability over real (UTC) time, one step per plate appearance."""
    timeline = win_prob_timeline(plays, win_prob)

    # Win probability holds until a play ends, then steps to its new value.
    times = [timeline["start_time_utc"].iloc[0], *timeline["end_time_utc"]]
    values = [timeline["home_wp_before"].iloc[0], *timeline["home_wp_after"]]
    hover = [
        "First pitch",
        *(
            f"{row.half.title()} {row.inning}: {row.event}<br>"
            f"{game.away_abbr} {row.away_score}, {game.home_abbr} {row.home_score}<br>"
            f"Change: {row.wp_delta:+.0%}"
            for row in timeline.itertuples()
        ),
    ]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=times,
            y=values,
            mode="lines",
            line={"shape": "hv", "width": 2, "color": "#1f4e79"},
            name=f"{game.home_abbr} win probability",
            text=hover,
            hovertemplate="%{x|%H:%M:%S} UTC<br>%{y:.0%}<br>%{text}<extra></extra>",
        )
    )

    scoring = timeline[timeline["is_scoring_play"]]
    figure.add_trace(
        go.Scatter(
            x=scoring["end_time_utc"],
            y=scoring["home_wp_after"],
            mode="markers",
            marker={"size": 9, "color": "#c0392b"},
            name="Scoring play",
            text=scoring["description"],
            hovertemplate="%{text}<extra></extra>",
        )
    )

    figure.add_hline(y=0.5, line_dash="dot", line_color="#999999")
    figure.update_layout(
        title=f"{game.away_team} @ {game.home_team}, {game.date} ({game.final_score})",
        xaxis_title="Time (UTC)",
        yaxis_title=f"{game.home_team} win probability",
        yaxis={"range": [0, 1], "tickformat": ".0%"},
        template="plotly_white",
        hovermode="closest",
        legend={"orientation": "h", "y": -0.2},
    )
    return figure


def comments_per_minute(comments: pd.DataFrame) -> pd.Series:
    """Comment count per UTC minute, with empty minutes filled in as zero."""
    return comments.set_index("created_utc").resample("1min").size().rename("comments")


def comment_volume_figure(game: pd.Series, comments: pd.DataFrame, title_suffix: str = "") -> go.Figure:
    per_minute = comments_per_minute(comments)
    figure = go.Figure(
        go.Bar(
            x=per_minute.index,
            y=per_minute.values,
            marker_color="#1f4e79",
            hovertemplate="%{x|%H:%M} UTC<br>%{y} comments<extra></extra>",
        )
    )
    figure.add_vline(x=game.start_time_utc, line_dash="dot", line_color="#c0392b")
    figure.update_layout(
        title=f"Comments per minute: {game.away_team} @ {game.home_team}, {game.date}{title_suffix}",
        xaxis_title="Time (UTC), dotted line = first pitch",
        yaxis_title="Comments per minute",
        template="plotly_white",
        bargap=0,
    )
    return figure


BIG_SWING = 0.10
# Fans react over the couple of minutes after a play ends (stream lag, typing).
REACTION_MINUTES = 2


def key_plays(timeline: pd.DataFrame, threshold: float = BIG_SWING) -> pd.DataFrame:
    """Scoring plays and plays that moved win probability by more than ``threshold``."""
    big_swing = timeline["wp_delta"].abs() > threshold
    plays = timeline[timeline["is_scoring_play"] | big_swing].copy()
    plays["kind"] = plays["is_scoring_play"].map({True: "Scoring play", False: "Big swing"})
    return plays


def reaction_table(plays: pd.DataFrame, comments: pd.DataFrame) -> pd.DataFrame:
    """For each play, comments per minute in the ``REACTION_MINUTES`` after it ended."""
    times = comments["created_utc"].sort_values().reset_index(drop=True)
    window = pd.Timedelta(minutes=REACTION_MINUTES)
    starts = times.searchsorted(plays["end_time_utc"])
    ends = times.searchsorted(plays["end_time_utc"] + window)
    out = plays.copy()
    out["reaction_per_min"] = (ends - starts) / REACTION_MINUTES
    return out


def volume_vs_win_prob_figure(game: pd.Series, plays: pd.DataFrame, win_prob: pd.DataFrame, comments: pd.DataFrame) -> go.Figure:
    """Comment volume per minute (bars) under the home win probability curve (line)."""
    timeline = win_prob_timeline(plays, win_prob)
    first_pitch, final_out = timeline["start_time_utc"].iloc[0], timeline["end_time_utc"].iloc[-1]
    pad = pd.Timedelta(minutes=20)
    in_view = comments[(comments["created_utc"] >= first_pitch - pad) & (comments["created_utc"] <= final_out + pad)]
    per_minute = comments_per_minute(in_view)

    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Bar(
            x=per_minute.index + pd.Timedelta(seconds=30),  # centre each bar on its minute
            y=per_minute.values,
            name="Comments per minute",
            marker_color="#b8c4d0",
            hovertemplate="%{x|%H:%M} UTC<br>%{y} comments<extra></extra>",
        ),
        secondary_y=False,
    )

    figure.add_trace(
        go.Scatter(
            x=[first_pitch, *timeline["end_time_utc"]],
            y=[timeline["home_wp_before"].iloc[0], *timeline["home_wp_after"]],
            mode="lines",
            line={"shape": "hv", "width": 2.5, "color": "#1f4e79"},
            name=f"{game.home_abbr} win probability",
            hovertemplate="%{x|%H:%M:%S} UTC<br>%{y:.0%}<extra></extra>",
        ),
        secondary_y=True,
    )

    marked = key_plays(timeline)
    styles = {"Scoring play": ("#c0392b", "circle"), "Big swing": ("#e67e22", "diamond")}
    for kind, (color, symbol) in styles.items():
        subset = marked[marked["kind"] == kind]
        figure.add_trace(
            go.Scatter(
                x=subset["end_time_utc"],
                y=subset["home_wp_after"],
                mode="markers",
                marker={"size": 11, "color": color, "symbol": symbol, "line": {"width": 1, "color": "white"}},
                name=kind if kind == "Scoring play" else f"Big swing (over {BIG_SWING:.0%})",
                text=[
                    f"{row.half.title()} {row.inning}: {row.description}<br>"
                    f"{game.away_abbr} {row.away_score}, {game.home_abbr} {row.home_score} "
                    f"({game.home_abbr} win probability {row.wp_delta:+.0%})"
                    for row in subset.itertuples()
                ],
                hovertemplate="%{x|%H:%M:%S} UTC<br>%{text}<extra></extra>",
            ),
            secondary_y=True,
        )

    figure.update_layout(
        title=f"Fan comment volume vs. win probability: {game.away_team} @ {game.home_team}, {game.date} ({game.final_score})",
        template="plotly_white",
        bargap=0,
        hovermode="closest",
        legend={"orientation": "h", "y": -0.15},
    )
    figure.update_xaxes(title_text="Time (UTC)")
    figure.update_yaxes(title_text="Comments per minute", secondary_y=False, showgrid=False)
    figure.update_yaxes(
        title_text=f"{game.home_team} win probability", range=[0, 1], tickformat=".0%", secondary_y=True
    )
    return figure


def write_html(figure: go.Figure, name: str) -> Path:
    path = reports_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(path, include_plotlyjs=True, full_html=True)
    return path
