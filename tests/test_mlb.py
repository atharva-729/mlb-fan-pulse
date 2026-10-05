import pandas as pd
import pytest

from mlb_fan_pulse.ingest import mlb


def _play(index, half, inning, home_score, away_score, scoring=False, complete=True):
    return {
        "about": {
            "atBatIndex": index,
            "halfInning": half,
            "inning": inning,
            "startTime": f"2025-09-30T22:0{index}:00.000Z",
            "endTime": f"2025-09-30T22:0{index}:30.500Z",
            "isComplete": complete,
            "isScoringPlay": scoring,
        },
        "result": {
            "event": "Single",
            "description": f"play {index}",
            "homeScore": home_score,
            "awayScore": away_score,
        },
        "matchup": {
            "batter": {"id": 100 + index, "fullName": f"Batter {index}"},
            "pitcher": {"id": 200, "fullName": "Pitcher"},
        },
    }


@pytest.fixture
def feed():
    return {
        "gameData": {
            "game": {"pk": 1},
            "datetime": {"officialDate": "2025-09-30", "dateTime": "2025-09-30T22:08:00Z"},
            "status": {"abstractGameState": "Final"},
            "teams": {
                "home": {"name": "New York Yankees", "abbreviation": "NYY", "teamName": "Yankees"},
                "away": {"name": "Boston Red Sox", "abbreviation": "BOS", "teamName": "Red Sox"},
            },
        },
        "liveData": {
            "linescore": {"teams": {"home": {"runs": 1}, "away": {"runs": 3}}},
            "plays": {
                "allPlays": [
                    _play(1, "bottom", 1, 1, 0, scoring=True),
                    _play(0, "top", 1, 0, 0),
                    _play(2, "top", 2, 1, 0, complete=False),
                ]
            },
        },
    }


def test_build_plays_flattens_sorts_and_parses_utc(feed):
    plays = mlb.build_plays(feed)

    assert list(plays["at_bat_index"]) == [0, 1]  # sorted, incomplete play dropped
    assert plays.loc[1, "half"] == "bottom"
    assert plays.loc[1, "is_scoring_play"]
    assert plays.loc[0, "batter_id"] == 100
    assert plays.loc[0, "end_time_utc"] == pd.Timestamp("2025-09-30T22:00:30.500Z")
    assert str(plays["start_time_utc"].dt.tz) == "UTC"


def test_build_games_uses_linescore(feed):
    game = mlb.build_games(feed, "AL Wild Card Series").iloc[0]

    assert (game.home_score, game.away_score) == (1, 3)
    assert game.final_score == "BOS 3 @ NYY 1"
    assert game.series_desc == "AL Wild Card Series"


def test_build_win_prob_converts_percent_and_derives_before():
    raw = [
        {"atBatIndex": 1, "homeTeamWinProbability": 40.0, "homeTeamWinProbabilityAdded": -12.2},
        {"atBatIndex": 0, "homeTeamWinProbability": 52.2, "homeTeamWinProbabilityAdded": 2.2},
    ]

    wp = mlb.build_win_prob(1, raw)

    assert list(wp["at_bat_index"]) == [0, 1]
    assert wp.loc[0, ["home_wp_before", "home_wp_after", "wp_delta"]].tolist() == [0.5, 0.522, 0.022]
    assert wp.loc[1, "home_wp_before"] == wp.loc[0, "home_wp_after"]


def _schedule_game(pk, away, home):
    return {
        "gamePk": pk,
        "status": {"abstractGameState": "Final"},
        "teams": {"away": {"team": {"name": away}}, "home": {"team": {"name": home}}},
    }


def test_find_game_pk_matches_teams(monkeypatch):
    games = [
        _schedule_game(10, "Detroit Tigers", "Cleveland Guardians"),
        _schedule_game(20, "Boston Red Sox", "New York Yankees"),
    ]
    monkeypatch.setattr(mlb, "fetch_schedule", lambda date: games)

    assert mlb.find_game_pk("2025-09-30", home="yankees", away="Red Sox") == 20
    with pytest.raises(mlb.GameLookupError, match="found 2"):
        mlb.find_game_pk("2025-09-30")
    with pytest.raises(mlb.GameLookupError, match="none"):
        mlb.find_game_pk("2025-09-30", home="Dodgers")
