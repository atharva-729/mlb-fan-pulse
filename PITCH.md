# MLB Fan Pulse: pitch notes

## The one-line answer

**We can measure how fans felt about every moment of a game, tie it to the exact play that caused it, and it already works on a real playoff game using free data.**

Say this first. Everything below supports it.

## Three reasons to believe it

### 1. Fan reaction tracks the game, play by play

Proven on the dev game: Red Sox 3, Yankees 1 (AL Wild Card Game 1, Sept 30, 2025).

| Moment | Comments per minute | vs. a typical minute (22) |
|---|---|---|
| Final out (Grisham strikes out) | 182 | 8.2x |
| Bellinger loads the bases, bottom 9 | 118 | 5.3x |
| Judge single, bottom 9 | 94 | 4.2x |
| Yoshida's go-ahead two-run single, top 7 | 85 | 3.9x |

- Across the 10 biggest plays, fans posted **73 comments per minute** afterwards, against **22** after ordinary plays.
- This is not just late-game buzz: inside innings 7 to 9 alone, big plays drew 75 per minute against 29 for the rest.

### 2. We can split the crowd by team, and the two sides feel differently

- 90% of commenters wear a team badge, so we know whose fan is talking: 984 comments from Yankees fans and 674 from Red Sox fans during this game, plus 3,557 from neutral fans.
- Red Sox fans started the game very negative (-0.57 on a -1 to 1 scale) and climbed to neutral (0.00) by the 9th as their team took the lead.
- Yankees fans went the other way, bottoming out at -0.34 in the top of the 9th.

### 3. It is cheap and the data is there

- **Cost so far: zero.** Game data comes from MLB's free stats feed; fan comments come from a free Reddit archive.
- **Volume is not a problem.** This one game thread had 5,924 usable comments. 2025 playoff threads ran 1,375 to 5,782 comments per game.
- **Nobody has published this for MLB.** Pieces exist elsewhere, but nothing links individual fan comments to specific plays, win probability and players.

## What to show (in this order)

1. **`reports/813074_volume_vs_win_prob.html`**: the headline chart. Grey bars are fan comments per minute, the blue line is the Yankees' chance of winning. Point at the 7th inning (line collapses, bars jump) and the 9th (the tallest bars of the night). Hover over the red dots to show the actual plays.
2. **`reports/813074_sentiment_by_fanbase.html`**: the two fanbases as two lines. Point at the Red Sox line rising while the Yankees line sags.

Open both in a browser before the pitch. They work offline.

## Where it goes next

The finished product is a one-page report per game with three parts:

- **Timeline**: what is on screen now.
- **Moments**: the top 5 to 8 fan reactions of the game, each with the play that caused it and a short summary of what fans were saying.
- **Perception vs. performance**: which players fans blamed or praised more than their actual contribution justified. This is the part with a story in it.

The same pipeline carries to other leagues (NFL, IPL): only the data source changes.

## Be upfront about these

- **One game so far.** The pattern is clear, but it is one game.
- **The mood scoring is still basic.** The current model reads tone, not target: the most "negative" comments of the night were fans complaining about ESPN's audio, not about the game. It also misses sarcasm. The next step, an AI model that reads each comment for who it is about, is designed to fix exactly this.
- **Internal use only for now.** MLB and Reddit data are fine for a prototype, but would need licensing or legal sign-off before anything goes to a client.
- **It runs after the game, not live.**

## The ask

- Go-ahead to finish the remaining steps (player-level sentiment, moments, the per-game report) and run it across a full playoff series.
- A small budget for an AI model API. Cost per game is not yet measured; the plan uses a small, cheap model.
