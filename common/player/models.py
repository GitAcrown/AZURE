"""Modèles runtime du store joueur (pas de contenu YAML)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GearInstance:
    id: int
    item_key: str
    durability: int | None


@dataclass(frozen=True)
class Stack:
    item_key: str
    quantity: int


@dataclass(frozen=True)
class EquippedSlot:
    slot: str
    gear_id: int | None = None
    item_key: str | None = None
    gear: GearInstance | None = None


@dataclass
class PlayerSnapshot:
    guild_id: int
    user_id: int
    energy: int
    energy_max: int
    energy_max_base: int
    money: int
    milieu_key: str | None
    created_at: str
    stacks: list[Stack] = field(default_factory=list)
    gear: list[GearInstance] = field(default_factory=list)
    equipped: dict[str, EquippedSlot] = field(default_factory=dict)
    created: bool = False
    coffee_minutes: int | None = None
    coffee_pct: float = 0.0
    dex_found: int = 0
    dex_total: int = 0
    fish_carry: int = 0
    fish_carry_max: int = 5
    creature_carry: int = 0
    creature_carry_max: int = 5
    travel_dest: str | None = None
    travel_arrives_at: str | None = None
    just_arrived: str | None = None
    archaeology_points: int = 0
    onboarding_done: bool = True

    def owned_keys(self) -> set[str]:
        keys = {s.item_key for s in self.stacks}
        keys.update(g.item_key for g in self.gear)
        for eq in self.equipped.values():
            if eq.item_key:
                keys.add(eq.item_key)
            if eq.gear is not None:
                keys.add(eq.gear.item_key)
        return keys


@dataclass(frozen=True)
class VillageTalkState:
    npc_key: str
    question: str
    response: str
    intent: str = "none"
    item_key: str | None = None
    milieu_key: str | None = None
    display: str = "none"
    board_keys: list[str] = field(default_factory=list)
    quantity: int = 1
    bucket: int = 0


@dataclass(frozen=True)
class CaughtSpecimen:
    id: int
    species_key: str
    length_cm: float
    weight_kg: float
    caught_at: str


@dataclass(frozen=True)
class DexRow:
    species_key: str
    catch_count: int
    first_caught_at: str
    best_length_cm: float | None = None
    best_weight_kg: float | None = None
    last_length_cm: float | None = None
    last_weight_kg: float | None = None


@dataclass
class PendingCast:
    guild_id: int
    user_id: int
    species_key: str
    method: str
    energy: int
    energy_max: int
    bait_consumed: str | None
    wait_s: float
    window_s: float
    trap_early: bool
    action_label: str
    milieu_key: str = ""
    weather_key: str = ""
    tool_key: str = ""
    hook_key: str | None = None
    bait_key: str | None = None
    resolved: bool = False
    preview: CastResult | None = None
    catch_view: object | None = None
    prep_task: object | None = None


@dataclass(frozen=True)
class CastResult:
    species_key: str
    catch_count: int
    is_new: bool
    energy: int
    energy_max: int
    bait_consumed: str | None
    snap: PlayerSnapshot | None = None
    length_cm: float | None = None
    weight_kg: float | None = None
    personal_record: bool = False
    guild_rank: int | None = None
    kept: bool = True
    carry_used: int = 0
    carry_max: int = 0
    waste_key: str | None = None
    loot_key: str | None = None
    hook_broke: bool = False
    daily_count: int | None = None
    daily_target: int = 0
    daily_just_rewarded: int = 0
    daily_note: bool = False
