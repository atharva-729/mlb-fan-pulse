# MLB Fan Pulse ⚾

**How did fans feel, moment by moment, and did it match what actually happened on the field?**

MLB Fan Pulse lines up Reddit game-thread comments with MLB play-by-play and win probability, for any game. It produces three things:

1. **A game timeline:** fan sentiment and comment volume over time, plotted on the win probability curve, with key plays marked.
2. **Moments:** spikes in comment volume or sentiment, each linked to the play that caused it, with a short summary of what fans were saying.
3. **Perception vs. performance:** how fans talked about each player compared with what that player actually contributed. The interesting part is where the two disagree.

This is an internal prototype / innovation pitch. It runs **in batch, after the game**. Nothing needs to run live.

---

## Feasibility (already checked)

| Question | Answer |
|---|---|
| Is there enough discussion? | Yes. In the 2025 postseason, r/baseball's neutral game threads alone got **1,375–5,782 comments per game** (median ≈ 3,760). That's about 15–20 comments per minute, with spikes on big plays. Team subreddits add more on top. |
| Where does the Reddit data come from? | The official Reddit API is closed to new developers. We use **Arctic Shift** (`https://arctic-shift.photon-reddit.com`), a free archive of Reddit data that runs about 30 seconds behind live. |
| Where does the game data come from? | The **MLB Stats API** (`https://statsapi.mlb.com`). Free, no key needed. |
| Has this been done before? | Pieces of it, but no public project links comment-level sentiment to specific plays and win probability with player-level breakdown. Nothing for MLB. |

**Licensing note:** Both MLB Stats API data and Reddit data are fine for an internal prototype or demo. Neither should go into a client deliverable without a license or legal sign-off. Keep this project internal.

**Seasonal caveat:** r/baseball game threads are nearly empty during the regular season. They're only busy in the postseason. For regular-season games, use team subreddits.

---

## Tech stack

Keep it simple. No servers, no databases beyond a file.

- **Python 3.11+**
- `requests`: Arctic Shift and MLB Stats API calls
- `duckdb` + Parquet: storage and queries
- `pandas`: data wrangling
- `transformers` + `cardiffnlp/twitter-roberta-base-sentiment-latest`: baseline sentiment model
- `rapidfuzz`: fuzzy player-name matching
- An LLM API (configurable, use a small, cheap model): targeted sentiment, sarcasm handling, moment summaries
- `plotly`: charts, exported as standalone HTML
- `pytest`: tests
- `python-dotenv`: config

---

## Repo structure

```
mlb-fan-pulse/
├── README.md
├── .env.example            # LLM_API_KEY, LLM_MODEL, etc.
├── pyproject.toml
├── config/
│   ├── games.yaml          # games to process (gamePk, subreddits, thread IDs)
│   └── nicknames.yaml      # player nickname → MLB person ID
├── data/
│   ├── raw/                # cached raw API responses (JSON), never re-fetch if present
│   └── processed/          # parquet tables
├── src/mlb_fan_pulse/
│   ├── http.py             # cached GET helper (retries, User-Agent, 429 handling)
│   ├── ingest/
│   │   ├── mlb.py          # schedule, live feed, win probability
│   │   └── reddit.py       # Arctic Shift: find threads, pull comments
│   ├── process/
│   │   ├── clean.py        # filter bots, deleted, junk
│   │   ├── sentiment.py    # baseline model + LLM targeted sentiment
│   │   ├── entities.py     # player linking
│   │   ├── align.py        # comment → play alignment
│   │   └── moments.py      # spike detection + summaries
│   ├── analysis/
│   │   └── players.py      # perception vs performance
│   ├── viz/
│   │   └── report.py       # per-game HTML report
│   └── cli.py              # `mlb-fan-pulse run --game <gamePk>`
├── notebooks/              # scratch exploration only
└── tests/
```

---

## Data model (Parquet tables)

| Table | Key columns |
|---|---|
| `games` | game_pk, date, home_team, away_team, final_score, series_desc |
| `plays` | game_pk, at_bat_index, inning, half, start_time_utc, end_time_utc, event, description, batter_id, pitcher_id, home_score, away_score |
| `win_prob` | game_pk, at_bat_index, home_wp_before, home_wp_after, wp_delta |
| `threads` | thread_id, subreddit, game_pk, thread_type (game / postgame), title, created_utc |
| `comments` | comment_id, thread_id, author, body, created_utc, score, parent_id |
| `comment_scores` | comment_id, base_sentiment (-1..1), llm_sentiment, target_player_id, target_type (player / manager / team / umpire / other), is_sarcastic |
| `comment_play_links` | comment_id, at_bat_index, link_weight |
| `moments` | game_pk, start_utc, end_utc, peak_volume, sentiment_shift, at_bat_index, summary |

All timestamps are **UTC**.

---

## Build phases

> **For Claude Code:** Build **one phase at a time**. At the end of each phase, stop, show the checkpoint output, and wait for review before starting the next one. Cache every raw API response under `data/raw/` and never re-fetch something that's already cached.

### Dev game

Use this game for all early phases:

**2025 AL Wild Card Series, Game 1: Red Sox @ Yankees (Sept 30, 2025).** The r/baseball game thread has about 5,782 comments.

Find its `gamePk` through the MLB schedule endpoint (`/api/v1/schedule?sportId=1&date=2025-09-30`). Don't hardcode a guessed ID.

---

### Phase 0: Setup

- Create the repo structure, `pyproject.toml`, `.env.example`, and a basic CLI skeleton.
- Write a small HTTP helper with retries, a polite User-Agent, and response caching to `data/raw/`.

✅ **Checkpoint:** `pip install -e .` works, `mlb-fan-pulse --help` runs, and `pytest` passes (even if empty).

---

### Phase 1: MLB game data

- `mlb.py`:
  - Look up the gamePk from the schedule.
  - Pull `/api/v1.1/game/{gamePk}/feed/live` and flatten `liveData.plays.allPlays` into the `plays` table, using each play's `about.startTime` / `about.endTime`.
  - Pull `/api/v1/game/{gamePk}/winProbability` and build the `win_prob` table. **Inspect the actual response first** to confirm field names, and join on `atBatIndex`.

✅ **Checkpoint:** Print the dev game's plays (inning, time, description, home win probability). Plot the win probability curve over real time. Sanity check: the final score in the data matches the actual result.

---

### Phase 2: Reddit data via Arctic Shift

- `reddit.py`:
  - **Find threads:** `/api/posts/search?author=BaseballBot&subreddit=baseball&after=...&before=...&fields=id,title,num_comments,created_utc`, then match the game thread to the game by team names and date.
  - Note: `title=` search **doesn't work** on very active subreddits (the API returns 422). Filter by `author` (the game-thread bot) and the date window instead. Team subreddits each use their own bot, so make the bot name configurable per subreddit in `games.yaml`.
  - **Pull comments:** `/api/comments/search?link_id=<id>&sort=asc&limit=100`, paging forward by `created_utc` until done. (`/api/comments/tree?link_id=t3_<id>&limit=9999` is a fallback.)
  - **Rate limits:** On a 429, read the `X-RateLimit-Reset` header, sleep that long, then retry. Make a few requests per second at most. This is a free service, so be gentle.
  - Note: `num_comments` and `score` only fill in about 36 hours after posting. That's fine for completed games.
- `clean.py`: Drop `[deleted]`/`[removed]` comments, AutoModerator, bot accounts, and empty bodies.

✅ **Checkpoint:** The dev game thread is fetched, and the comment count is close to Reddit's number (about 5.7k; some loss from deletions is expected). Plot a histogram of comments per minute. Print 20 random comments to eyeball the quality.

---

### Phase 3: First visual (volume vs. win probability) 🎯

This is the earliest point where there's something to show.

- Bucket comments per minute. Overlay comment volume on the win probability curve. Mark scoring plays and big win probability swings (|wp_delta| > 0.10).
- Export as standalone HTML.

✅ **Checkpoint:** An HTML chart for the dev game where volume spikes visibly line up with big plays. If they don't, investigate time zones or timestamp parsing before going further.

---

### Phase 4: Baseline sentiment

- `sentiment.py`: Run the cardiffnlp RoBERTa model on every comment, mapping the output to a score from -1 to 1. Batch the inference and cache the results.
- Aggregate sentiment by minute and by half-inning. Use half-inning as the main unit, since that's where the signal is stable; per-minute is noisy.
- Note: In r/baseball's neutral threads, both fanbases are mixed together. Use `author_flair_text` (the user's team flair) to split comments by fanbase where it's available. **This matters a lot:** a home run is joy for one side and despair for the other.

✅ **Checkpoint:** Sentiment by fanbase over time on the same chart. A gut check: when one team scores, its fans' sentiment goes up and the other side's goes down.

---

### Phase 5: Player linking + targeted sentiment (LLM)

- `entities.py`:
  - Build a player dictionary from the game's rosters (Stats API) and `nicknames.yaml`.
  - Match with `rapidfuzz`, keeping only plausible names for players in this game.
- LLM pass, sent in batches of about 50 comments per call. Give the model game context: score, inning, and the last few plays. For each comment, ask:
  - Who is the comment about (player ID / manager / umpire / team / other)?
  - Sentiment toward that target, from -1 to 1.
  - Is it sarcastic?
  - Return strict JSON and validate it.
- Cache LLM results by comment_id. Log token usage and cost per game.
- Hand-label about 200 comments to measure accuracy against the baseline model and the LLM.

✅ **Checkpoint:** An accuracy table (baseline vs. LLM) on the labeled set, and the cost per game. Show the top 5 most-discussed players with their average sentiment.

---

### Phase 6: Linking comments to plays + moments

- `align.py`: Link each comment to the plays that ended 0–180 seconds before it was posted, weighting closer plays more (for example, exponential decay). Fans react with a delay because of stream lag and typing time. Tune the window by checking whether volume spikes line up best with play end times.
- `moments.py`:
  - Find spikes with a rolling z-score on comment volume and on sentiment change.
  - Attach each spike to its most likely play.
  - Have the LLM write a 1–2 sentence summary of fan reaction from a sample of that moment's comments.

✅ **Checkpoint:** The top 5–8 moments for the dev game, each with its play description and summary. Read them: do they match how the game actually went?

---

### Phase 7: Perception vs. performance

- `players.py`:
  - Compute each player's actual contribution as **WPA** (win probability added): the sum of `wp_delta` on plays where he was the batter (or the negative of it for the pitcher).
  - Compare against fan sentiment toward him and how much he was discussed.
  - Flag the biggest gaps: "blamed more than his WPA justifies" and "a hero beyond his numbers."

✅ **Checkpoint:** A scatter plot of WPA vs. fan sentiment, with labeled outliers, plus a short written list of the gaps.

---

### Phase 8: Game report + scaling

- `report.py`: One standalone HTML report per game containing the timeline, moments, and player table.
- `mlb-fan-pulse run --game <gamePk>` runs the whole pipeline end to end (cached, so reruns are cheap).
- Run it across a full series and add team subreddit threads as a second source.

✅ **Checkpoint:** Reports for every game in one 2025 series, plus one 2026 postseason game run the morning after it was played.

---

### Stretch (later, not now)

- **Series arcs:** How a fanbase's mood shifts game by game through a series.
- **Second source:** Bluesky (its Jetstream feed is open and real-time, but has no history, so it needs a listener running during games). Keep `ingest/` built behind a common interface so sources can be swapped.
- **Other sports:** NFL (game threads on r/nfl + nflverse play-by-play) and IPL (r/Cricket match threads + Cricsheet ball-by-ball data). The pipeline is the same; only the ingest step changes.

---

## Known gotchas

- **Stream delay:** Reactions lag plays by anywhere from seconds to minutes. Don't match to the nearest timestamp; use the decay window.
- **Spoilers from fast streams:** Some fans see a play before others, so a few comments come before the play. Allow a small negative window (about -15 seconds) if the data shows it.
- **Sarcasm:** Baseball fans are deeply sarcastic ("great, another walk, love that"). This is why the LLM pass exists.
- **Mixed fanbases:** In neutral threads, always split by flair before reading anything into the sentiment.
- **Nicknames:** Fans use short or alternate names, and words like "our closer" or "the ump." Grow `nicknames.yaml` as you go.
- **Arctic Shift reliability:** It's one person's free project with no uptime guarantees. Cache everything you fetch.