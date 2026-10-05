"""Reddit game threads and comments via Arctic Shift.

Builds the ``threads`` and ``comments_raw`` tables. All timestamps are UTC.
Arctic Shift is a free, one-person service: every page is cached and uncached
requests are spaced out.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from mlb_fan_pulse import config, http, storage

log = logging.getLogger(__name__)

BASE_URL = "https://arctic-shift.photon-reddit.com"

PAGE_SIZE = 100
REQUEST_SPACING_SECONDS = 0.5
# Arctic Shift answers 422 when a query times out on its side; a retry usually works.
RETRY_STATUSES = http.RETRY_STATUSES | {422}
# num_comments and score only settle about 36 hours after posting, so younger
# threads are fetched but not cached.
SETTLED_AFTER_SECONDS = 48 * 3600

POST_FIELDS = "id,title,num_comments,created_utc,subreddit,author"
COMMENT_FIELDS = "id,link_id,parent_id,author,body,created_utc,score,author_flair_text"

# How far around first pitch to look for the bot's threads.
SEARCH_BEFORE_START = pd.Timedelta(hours=8)
SEARCH_AFTER_START = pd.Timedelta(hours=12)


class ThreadLookupError(LookupError):
    pass


def _get(path: str, params: dict[str, Any], *, settled: bool) -> list[dict]:
    url = f"{BASE_URL}{path}"
    was_cached = http.cache_path(url, params).exists()
    response = http.get_json(url, params, cache_if=lambda _: settled, retry_statuses=RETRY_STATUSES)
    if not was_cached:
        time.sleep(REQUEST_SPACING_SECONDS)
    return response.get("data") or []


def _is_settled(created_utc: float) -> bool:
    return time.time() - created_utc > SETTLED_AFTER_SECONDS


def thread_type(title: str) -> str | None:
    lowered = title.lower()
    if lowered.startswith(("postgame thread", "post game thread", "post-game thread")):
        return "postgame"
    if lowered.startswith("game thread"):
        return "game"
    return None


def match_threads(posts: list[dict], game: pd.Series) -> list[dict]:
    """Pick the game thread and postgame thread for ``game`` out of a bot's posts.

    Matches on both club names in the title. On a doubleheader day several
    threads match, so take the game thread posted closest to first pitch and
    the first postgame thread after it.
    """
    start = game.start_time_utc.timestamp()
    names = (game.home_name.lower(), game.away_name.lower())
    candidates = [p for p in posts if all(name in p["title"].lower() for name in names)]

    game_threads = [p for p in candidates if thread_type(p["title"]) == "game"]
    postgame_threads = [
        p for p in candidates if thread_type(p["title"]) == "postgame" and p["created_utc"] > start
    ]

    picked = []
    if game_threads:
        picked.append(min(game_threads, key=lambda p: abs(p["created_utc"] - start)))
    if postgame_threads:
        picked.append(min(postgame_threads, key=lambda p: p["created_utc"]))
    return picked


def find_threads(game: pd.Series, subreddit: str, bot: str) -> list[dict]:
    """Search a subreddit for the bot's threads around the game and match them.

    Title search returns 422 on busy subreddits, so filter by author and a
    time window instead.
    """
    start = game.start_time_utc
    posts = _get(
        "/api/posts/search",
        {
            "author": bot,
            "subreddit": subreddit,
            "after": int((start - SEARCH_BEFORE_START).timestamp()),
            "before": int((start + SEARCH_AFTER_START).timestamp()),
            "fields": POST_FIELDS,
            "limit": PAGE_SIZE,
        },
        settled=_is_settled((start + SEARCH_AFTER_START).timestamp()),
    )
    return match_threads(posts, game)


def fetch_threads_by_id(thread_ids: list[str]) -> list[dict]:
    """Threads pinned by hand in ``games.yaml``. One small request, not cached."""
    return _get("/api/posts/ids", {"ids": ",".join(thread_ids), "fields": POST_FIELDS}, settled=False)


def fetch_comments(thread_id: str, thread_created_utc: float) -> list[dict]:
    """All comments in a thread, oldest first.

    ``after`` is exclusive and comments often share a second, so each page
    starts one second back from the last comment seen and duplicates are
    dropped by id. Paging stops when a page brings nothing new.
    """
    settled = _is_settled(thread_created_utc)
    seen: dict[str, dict] = {}
    after: int | None = None

    while True:
        params: dict[str, Any] = {
            "link_id": thread_id,
            "sort": "asc",
            "limit": PAGE_SIZE,
            "fields": COMMENT_FIELDS,
        }
        if after is not None:
            params["after"] = after
        page = _get("/api/comments/search", params, settled=settled)

        new = [c for c in page if c["id"] not in seen]
        for comment in new:
            seen[comment["id"]] = comment
        if not page:
            break

        last = int(page[-1]["created_utc"])
        if new:
            after = last - 1
        elif len(page) < PAGE_SIZE:
            break
        else:
            # A full page of already-seen comments: a single second holds more
            # than a page. Step past it rather than loop forever.
            log.warning("thread %s: more than %d comments at second %d", thread_id, PAGE_SIZE, last)
            after = last
        log.debug("thread %s: %d comments so far", thread_id, len(seen))

    return sorted(seen.values(), key=lambda c: (c["created_utc"], c["id"]))


def build_threads(posts: list[dict], game_pk: int) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "thread_id": p["id"],
                "subreddit": p["subreddit"],
                "game_pk": game_pk,
                "thread_type": thread_type(p["title"]) or "other",
                "title": p["title"],
                "created_utc": p["created_utc"],
                "num_comments": p.get("num_comments"),
            }
            for p in posts
        ]
    )
    frame["created_utc"] = pd.to_datetime(frame["created_utc"], unit="s", utc=True)
    return frame


def build_comments(comments: list[dict], thread_id: str) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "comment_id": c["id"],
                "thread_id": thread_id,
                "author": c.get("author"),
                "body": c.get("body"),
                "created_utc": c["created_utc"],
                "score": c.get("score"),
                "parent_id": c.get("parent_id"),
                "author_flair_text": c.get("author_flair_text"),
            }
            for c in comments
        ],
        columns=[
            "comment_id",
            "thread_id",
            "author",
            "body",
            "created_utc",
            "score",
            "parent_id",
            "author_flair_text",
        ],
    )
    frame["created_utc"] = pd.to_datetime(frame["created_utc"], unit="s", utc=True)
    return frame


def ingest_game(game: pd.Series) -> dict[str, pd.DataFrame]:
    """Find and pull every configured subreddit's threads for one game."""
    game_pk = int(game.game_pk)
    posts: list[dict] = []
    for subreddit in config.game_subreddits(game_pk):
        if subreddit.get("thread_ids"):
            found = fetch_threads_by_id(subreddit["thread_ids"])
        else:
            found = find_threads(game, subreddit["name"], subreddit["bot"])
        if not any(thread_type(p["title"]) == "game" for p in found):
            raise ThreadLookupError(
                f"no game thread found in r/{subreddit['name']} by u/{subreddit.get('bot')} "
                f"for {game.away_name} @ {game.home_name} on {game.date}"
            )
        posts.extend(found)

    threads = build_threads(posts, game_pk)
    comments = pd.concat(
        [build_comments(fetch_comments(p["id"], p["created_utc"]), p["id"]) for p in posts],
        ignore_index=True,
    )

    storage.write_table("threads", game_pk, threads)
    storage.write_table("comments_raw", game_pk, comments)
    return {"threads": threads, "comments_raw": comments}
