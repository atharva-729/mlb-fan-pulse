import pandas as pd
import pytest

from mlb_fan_pulse.process import sentiment

T0 = pd.Timestamp("2025-09-30T22:00:00Z")


def _at(minutes):
    return T0 + pd.Timedelta(minutes=minutes)


def test_preprocess_normalises_links_users_and_media():
    text = "u/someone look  at https://example.com/x ![gif](giphy|abc)\nwow"

    assert sentiment.preprocess(text) == "@user look at http wow"


@pytest.mark.parametrize(
    "flair, expected",
    [
        (":nyy: New York Yankees", "home"),
        (":nyypride: New York Yankees", "home"),
        (":bos: Boston Red Sox", "away"),
        (":lad2: Los Angeles Dodgers", "other"),
        (":mlb: Major League Baseball", "other"),
        (None, "none"),
        (float("nan"), "none"),
        (":nyy:", "none"),
    ],
)
def test_fanbase(flair, expected):
    assert sentiment.fanbase(flair, "New York Yankees", "Boston Red Sox") == expected


@pytest.fixture
def plays():
    return pd.DataFrame(
        {
            "at_bat_index": [0, 1, 2, 3],
            "inning": [1, 1, 1, 2],
            "half": ["top", "top", "bottom", "top"],
            "start_time_utc": [_at(0), _at(3), _at(10), _at(20)],
            "end_time_utc": [_at(2), _at(6), _at(15), _at(25)],
            "is_scoring_play": [False, False, True, False],
            "description": ["out", "out", "homer", "out"],
        }
    )


def test_half_innings_in_game_order(plays):
    halves = sentiment.half_innings(plays)

    assert list(halves["half_inning"]) == ["T1", "B1", "T2"]
    assert halves.loc[0, "start_utc"] == _at(0) and halves.loc[0, "end_utc"] == _at(6)


def test_assign_half_inning_uses_breaks_and_drops_pre_and_postgame(plays):
    comments = pd.DataFrame(
        {
            "comment_id": ["pre", "t1", "break", "b1", "t2", "grace", "post"],
            "created_utc": [_at(-5), _at(1), _at(8), _at(12), _at(21), _at(29), _at(31)],
        }
    )

    comments["created_utc"] = comments["created_utc"].astype("datetime64[ms, UTC]")  # as read back from parquet

    tagged = sentiment.assign_half_inning(comments, sentiment.half_innings(plays))

    assert dict(zip(tagged["comment_id"], tagged["half_inning"])) == {
        "t1": "T1",
        "break": "T1",  # typed in the break after the top of the 1st
        "b1": "B1",
        "t2": "T2",
        "grace": "T2",  # within 5 minutes of the final out
    }


def test_by_half_inning_means_per_fanbase(plays):
    halves = sentiment.half_innings(plays)
    tagged = pd.DataFrame(
        {
            "half_inning": ["T1", "T1", "T1", "B1"],
            "fanbase": ["home", "home", "away", "home"],
            "base_sentiment": [0.5, -0.1, -0.8, 0.9],
        }
    )

    result = sentiment.by_half_inning(tagged, halves).set_index(["half_inning", "fanbase"])

    assert result.loc[("T1", "home"), "sentiment"] == pytest.approx(0.2)
    assert result.loc[("T1", "home"), "comments"] == 2
    assert result.loc[("T1", "away"), "sentiment"] == pytest.approx(-0.8)
    assert result.loc[("T1", "home"), "mid_utc"] == _at(3)


def test_scoring_reactions_before_and_after(plays):
    # The homer ends at minute 15 in the bottom half, so the home side scored.
    scored = pd.DataFrame(
        {
            "created_utc": [_at(13), _at(14), _at(16), _at(13), _at(16), _at(17), _at(19)],
            "fanbase": ["home", "home", "home", "away", "away", "away", "away"],
            "base_sentiment": [0.0, -0.2, 0.9, 0.1, -0.7, -0.5, 1.0],
        }
    )

    row = sentiment.scoring_reactions(scored, plays).iloc[0]

    assert row.scoring_side == "home"
    assert row.home_before == pytest.approx(-0.1) and row.home_after == pytest.approx(0.9)
    assert row.away_before == pytest.approx(0.1) and row.away_after == pytest.approx(-0.6)  # minute 19 is outside
    assert (row.home_n_after, row.away_n_after) == (1, 2)
