import pandas as pd
import pytest

from mlb_fan_pulse.viz import charts

T0 = pd.Timestamp("2025-09-30T22:00:00Z")


def _at(seconds):
    return T0 + pd.Timedelta(seconds=seconds)


@pytest.fixture
def timeline():
    return pd.DataFrame(
        {
            "at_bat_index": [0, 1, 2, 3],
            "end_time_utc": [_at(60), _at(300), _at(600), _at(900)],
            "wp_delta": [0.02, -0.17, 0.11, -0.10],
            "is_scoring_play": [False, True, False, False],
        }
    )


def test_key_plays_keeps_scoring_plays_and_swings_over_threshold(timeline):
    marked = charts.key_plays(timeline)

    # -0.10 is not over the threshold; the scoring play is labelled as scoring even though it is also a big swing.
    assert list(marked["at_bat_index"]) == [1, 2]
    assert list(marked["kind"]) == ["Scoring play", "Big swing"]


def test_reaction_table_counts_comments_in_window_after_play(timeline):
    seconds = [30, 61, 100, 179, 181, 310, 320]
    comments = pd.DataFrame({"created_utc": [_at(s) for s in reversed(seconds)]})

    reactions = charts.reaction_table(timeline, comments)

    # Play 0 ends at 60s: comments at 61, 100, 179 fall in the next 2 minutes; 181 does not.
    assert list(reactions["reaction_per_min"]) == [1.5, 1.0, 0.0, 0.0]


def test_comments_per_minute_fills_empty_minutes():
    comments = pd.DataFrame({"created_utc": [_at(5), _at(20), _at(185)]})

    per_minute = charts.comments_per_minute(comments)

    assert list(per_minute) == [2, 0, 0, 1]
