"""Plotly figures, exported as standalone HTML."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

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


def write_html(figure: go.Figure, name: str) -> Path:
    path = reports_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(path, include_plotlyjs=True, full_html=True)
    return path
