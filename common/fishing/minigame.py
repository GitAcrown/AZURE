"""Timings du mini-jeu canne / filet (fonctions pures)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from common.catalog import Item
from common.catalog.models import MinigameSettings


@dataclass(frozen=True)
class BiteTimings:
    wait_s: float
    window_s: float
    trap_early: bool
    action_label: str
    method: str


def hook_window_multiplier(hook: Item | None) -> float:
    if hook is None:
        return 1.0
    raw = (hook.effects or {}).get("minigame") or {}
    try:
        value = float(raw.get("hook_window_multiplier") or 1.0)
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0


def bite_timings(
    settings: MinigameSettings,
    method: str,
    *,
    hook: Item | None = None,
    rng: random.Random | None = None,
) -> BiteTimings:
    rng = rng or random.Random()
    if method == "net":
        return BiteTimings(
            wait_s=float(settings.net_wait_s),
            window_s=float(settings.net_window_s),
            trap_early=False,
            action_label="Ramasser",
            method="net",
        )
    wait = rng.uniform(settings.rod_wait_min_s, settings.rod_wait_max_s)
    window = float(settings.rod_window_s) * hook_window_multiplier(hook)
    return BiteTimings(
        wait_s=wait,
        window_s=max(0.15, window),
        trap_early=True,
        action_label="Ferrer",
        method="rod",
    )
