"""Paths and environment-driven settings."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from mlb_fan_pulse import __version__

# src/mlb_fan_pulse/config.py -> repo root (the project is installed editable).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_USER_AGENT = f"mlb-fan-pulse/{__version__} (internal prototype)"


def data_dir() -> Path:
    override = os.getenv("MLB_FAN_PULSE_DATA_DIR")
    return Path(override) if override else PROJECT_ROOT / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def processed_dir() -> Path:
    return data_dir() / "processed"


DEFAULT_SUBREDDITS = [{"name": "baseball", "bot": "BaseballBot", "thread_ids": []}]


def game_subreddits(game_pk: int) -> list[dict]:
    """Subreddits (with their game-thread bot) to pull for a game, from ``config/games.yaml``."""
    path = PROJECT_ROOT / "config" / "games.yaml"
    if not path.exists():
        return DEFAULT_SUBREDDITS
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for game in loaded.get("games") or []:
        if game.get("game_pk") == game_pk and game.get("subreddits"):
            return game["subreddits"]
    return DEFAULT_SUBREDDITS


def user_agent() -> str:
    return os.getenv("MLB_FAN_PULSE_USER_AGENT") or DEFAULT_USER_AGENT
