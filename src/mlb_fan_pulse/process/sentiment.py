"""Baseline sentiment (cardiffnlp RoBERTa) and its aggregation by fanbase.

The model run needs ``torch`` and is done on Google Colab with
``notebooks/baseline_sentiment_colab.ipynb``, which writes the ``comment_scores``
table. Everything else here is light and runs locally on that table.
"""

from __future__ import annotations

import re

import pandas as pd

MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
MAX_TOKENS = 256

_MEDIA_EMBED = re.compile(r"!\[(?:gif|img)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_USER = re.compile(r"(?<!\w)/?u/[\w-]+")
_FLAIR_EMOJI = re.compile(r":[\w-]+:")

FANBASES = ("home", "away", "other", "none")


def preprocess(text: str) -> str:
    """Normalise a Reddit comment the way the model's Twitter training data was."""
    text = _MEDIA_EMBED.sub("", text)
    text = _URL.sub("http", text)
    text = _USER.sub("@user", text)
    return " ".join(text.split())


def score_texts(texts: list[str], batch_size: int = 64, device: str | None = None) -> pd.DataFrame:
    """Run the baseline model. Returns base_neg/base_neu/base_pos and base_sentiment in -1..1.

    ``base_sentiment`` is P(positive) - P(negative). Requires the ``nlp`` extra.
    """
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME).to(device).eval()
    labels = [model.config.id2label[i].lower() for i in range(model.config.num_labels)]

    cleaned = [preprocess(t) for t in texts]
    # Similar lengths together keeps padding (and so runtime) down.
    order = sorted(range(len(cleaned)), key=lambda i: len(cleaned[i]))
    probabilities = [None] * len(cleaned)
    with torch.no_grad():
        for start in range(0, len(order), batch_size):
            indices = order[start : start + batch_size]
            encoded = tokenizer(
                [cleaned[i] for i in indices], padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt"
            ).to(device)
            batch = torch.softmax(model(**encoded).logits, dim=-1).cpu().tolist()
            for i, row in zip(indices, batch):
                probabilities[i] = row

    scores = pd.DataFrame(probabilities, columns=[f"base_{label[:3]}" for label in labels])
    scores["base_sentiment"] = scores["base_pos"] - scores["base_neg"]
    return scores[["base_sentiment", "base_neg", "base_neu", "base_pos"]]


def fanbase(flair: str | None, home_team: str, away_team: str) -> str:
    """Which side a commenter is on, from their r/baseball team flair.

    ``home`` / ``away`` for the two clubs playing, ``other`` for any other
    flair, ``none`` when there is no flair.
    """
    if flair is None or pd.isna(flair):
        return "none"
    text = _FLAIR_EMOJI.sub("", flair).strip().lower()
    if not text:
        return "none"
    if home_team.lower() in text:
        return "home"
    if away_team.lower() in text:
        return "away"
    return "other"


def with_fanbase(comments: pd.DataFrame, game: pd.Series) -> pd.DataFrame:
    out = comments.copy()
    out["fanbase"] = [fanbase(f, game.home_team, game.away_team) for f in out["author_flair_text"]]
    return out


def half_innings(plays: pd.DataFrame) -> pd.DataFrame:
    """One row per half-inning with its real-time span, in game order."""
    halves = (
        plays.groupby(["inning", "half"], as_index=False)
        .agg(start_utc=("start_time_utc", "min"), end_utc=("end_time_utc", "max"))
        .sort_values("start_utc")
        .reset_index(drop=True)
    )
    halves["half_inning"] = [f"{half[0].upper()}{inning}" for inning, half in zip(halves["inning"], halves["half"])]
    return halves


def assign_half_inning(comments: pd.DataFrame, halves: pd.DataFrame, grace_minutes: int = 5) -> pd.DataFrame:
    """Tag each comment with the half-inning it was posted in.

    A half-inning runs until the next one starts, so reactions typed during the
    break still count toward the half they are about. Comments before first
    pitch, or more than ``grace_minutes`` after the final out, are dropped.
    """
    # merge_asof needs identical key dtypes; parquet round-trips can differ in time resolution.
    unit = "datetime64[ns, UTC]"
    ordered = comments.astype({"created_utc": unit}).sort_values("created_utc")
    tagged = pd.merge_asof(
        ordered,
        halves[["start_utc", "half_inning", "inning", "half"]].astype({"start_utc": unit}),
        left_on="created_utc",
        right_on="start_utc",
    )
    cutoff = halves["end_utc"].max() + pd.Timedelta(minutes=grace_minutes)
    return tagged[tagged["half_inning"].notna() & (tagged["created_utc"] <= cutoff)].drop(columns="start_utc")


def by_half_inning(tagged: pd.DataFrame, halves: pd.DataFrame) -> pd.DataFrame:
    """Mean sentiment and comment count per half-inning and fanbase."""
    grouped = (
        tagged.groupby(["half_inning", "fanbase"], as_index=False)
        .agg(sentiment=("base_sentiment", "mean"), comments=("base_sentiment", "size"))
        .merge(halves[["half_inning", "start_utc", "end_utc"]], on="half_inning")
        .sort_values(["start_utc", "fanbase"])
        .reset_index(drop=True)
    )
    grouped["mid_utc"] = grouped["start_utc"] + (grouped["end_utc"] - grouped["start_utc"]) / 2
    return grouped


def by_minute(tagged: pd.DataFrame) -> pd.DataFrame:
    """Mean sentiment and comment count per minute and fanbase. Noisy; half-inning is the main unit."""
    return (
        tagged.assign(minute=tagged["created_utc"].dt.floor("1min"))
        .groupby(["minute", "fanbase"], as_index=False)
        .agg(sentiment=("base_sentiment", "mean"), comments=("base_sentiment", "size"))
    )


def scoring_reactions(scored: pd.DataFrame, plays: pd.DataFrame, window_minutes: int = 3) -> pd.DataFrame:
    """Each fanbase's mean sentiment in the minutes before and after every scoring play.

    The gut check: the scoring side's fans should go up, the other side's down.
    """
    window = pd.Timedelta(minutes=window_minutes)
    rows = []
    for play in plays[plays["is_scoring_play"]].itertuples():
        scoring_side = "away" if play.half == "top" else "home"
        row = {
            "at_bat_index": play.at_bat_index,
            "end_time_utc": play.end_time_utc,
            "half_inning": f"{play.half[0].upper()}{play.inning}",
            "description": play.description,
            "scoring_side": scoring_side,
        }
        for side in ("home", "away"):
            fans = scored[scored["fanbase"] == side]
            before = fans[(fans["created_utc"] >= play.end_time_utc - window) & (fans["created_utc"] < play.end_time_utc)]
            after = fans[(fans["created_utc"] >= play.end_time_utc) & (fans["created_utc"] < play.end_time_utc + window)]
            row[f"{side}_before"] = before["base_sentiment"].mean()
            row[f"{side}_after"] = after["base_sentiment"].mean()
            row[f"{side}_n_before"] = len(before)
            row[f"{side}_n_after"] = len(after)
        rows.append(row)
    return pd.DataFrame(rows)
