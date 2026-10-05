import pandas as pd
import pytest

from mlb_fan_pulse.ingest import reddit
from mlb_fan_pulse.process import clean

START = pd.Timestamp("2025-09-30T22:08:00Z")


@pytest.fixture
def game():
    return pd.Series(
        {"game_pk": 1, "date": "2025-09-30", "home_name": "Yankees", "away_name": "Red Sox", "start_time_utc": START}
    )


def _post(post_id, title, hours_from_start):
    return {
        "id": post_id,
        "title": title,
        "created_utc": int(START.timestamp() + hours_from_start * 3600),
        "subreddit": "baseball",
        "num_comments": 10,
    }


def test_thread_type():
    assert reddit.thread_type("Game Thread: AL Wild Card Series Game 1 ⚾ Red Sox (0) @ Yankees (0)") == "game"
    assert reddit.thread_type("Postgame Thread ⚾ Red Sox 3 @ Yankees 1") == "postgame"
    assert reddit.thread_type("[General Discussion] Around the Horn & Game Thread Index") is None


def test_match_threads_picks_this_games_threads(game):
    posts = [
        _post("idx", "[General Discussion] Around the Horn & Game Thread Index - 9/30/25", -17),
        _post("other", "Game Thread: NL Wild Card Series Game 1 ⚾ Reds (0) @ Dodgers (0)", 2),
        _post("gt", "Game Thread: AL Wild Card Series Game 1 ⚾ Red Sox (0) @ Yankees (0) - 6:08 PM ET", -1),
        _post("pg", "Postgame Thread ⚾ Red Sox 3 @ Yankees 1", 3.2),
    ]

    assert [p["id"] for p in reddit.match_threads(posts, game)] == ["gt", "pg"]


def test_match_threads_doubleheader_takes_closest_to_first_pitch(game):
    posts = [
        _post("gt1", "Game Thread: Red Sox (0) @ Yankees (0) - 1:05 PM ET", -6),
        _post("pg1", "Postgame Thread ⚾ Red Sox 1 @ Yankees 2", -2),
        _post("gt2", "Game Thread: Red Sox (0) @ Yankees (0) - 6:08 PM ET", -1),
        _post("pg2", "Postgame Thread ⚾ Red Sox 3 @ Yankees 1", 3),
    ]

    assert [p["id"] for p in reddit.match_threads(posts, game)] == ["gt2", "pg2"]


def _comment(comment_id, second):
    return {"id": comment_id, "created_utc": second, "body": "x", "author": "a", "link_id": "t3_t", "parent_id": "t3_t"}


def test_fetch_comments_pages_without_losing_same_second_comments(monkeypatch):
    """Arctic Shift's ``after`` is exclusive, so comments sharing the boundary second must not be lost."""
    monkeypatch.setattr(reddit, "PAGE_SIZE", 3)
    everything = [_comment("a", 10), _comment("b", 11), _comment("c", 12), _comment("d", 12), _comment("e", 15)]
    requests_made = []

    def fake_get(path, params, *, settled):
        requests_made.append(params.get("after"))
        after = params.get("after", -1)
        return [c for c in everything if c["created_utc"] > after][: params["limit"]]

    monkeypatch.setattr(reddit, "_get", fake_get)

    comments = reddit.fetch_comments("t", thread_created_utc=0)

    assert [c["id"] for c in comments] == ["a", "b", "c", "d", "e"]
    assert requests_made == [None, 11, 14]


def test_fetch_comments_empty_thread(monkeypatch):
    monkeypatch.setattr(reddit, "_get", lambda path, params, *, settled: [])

    assert reddit.fetch_comments("t", thread_created_utc=0) == []
    assert reddit.build_comments([], "t").empty


def test_build_comments_parses_utc():
    frame = reddit.build_comments(
        [{"id": "c1", "created_utc": 1759266739, "body": "hi", "author": "a", "score": 4, "parent_id": "t3_t"}], "t"
    )

    assert frame.loc[0, "created_utc"] == pd.Timestamp("2025-09-30T21:12:19Z")
    assert frame.loc[0, "thread_id"] == "t"
    assert frame.loc[0, "author_flair_text"] is None


@pytest.mark.parametrize(
    "author, body, expected",
    [
        ("fan", "[deleted]", "deleted"),
        ("fan", "[removed]", "deleted"),
        ("AutoModerator", "Please read the rules", "bot"),
        ("BaseballBot", "Line score", "bot"),
        ("stats_bot", "here are stats", "bot"),
        ("fan", "   ", "empty"),
        ("fan", None, "empty"),
        ("fan", "![gif](giphy|kCrGOt5ojlVbG)", "media_only"),
        ("fan", "![gif](giphy|abc) LET'S GO", None),
        ("Talbot", "great, another walk, love that", None),
        ("[deleted]", "still a real comment", None),
    ],
)
def test_drop_reason(author, body, expected):
    assert clean.drop_reason(author, body) == expected


def test_clean_comments_counts_drops():
    comments = pd.DataFrame(
        {
            "comment_id": ["1", "2", "3"],
            "author": ["fan", "AutoModerator", "fan"],
            "body": ["nice hit", "rules", "[deleted]"],
        }
    )

    kept, dropped = clean.clean_comments(comments)

    assert list(kept["comment_id"]) == ["1"]
    assert dropped.to_dict() == {"deleted": 1, "bot": 1, "empty": 0, "media_only": 0}
