"""Modèles Pydantic du contenu YAML AZURE.

Les YAML restent la source de vérité. `extra='allow'` conserve les champs
futurs sans les hardcoder ici.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ContentModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class SpeciesAssets(_ContentModel):
    sprite: str
    shadow: str


class SpeciesBiology(_ContentModel):
    min_length_cm: Optional[float] = None
    max_length_cm: Optional[float] = None
    min_weight_kg: Optional[float] = None
    max_weight_kg: Optional[float] = None

    def is_incomplete(self) -> bool:
        return any(
            v is None
            for v in (
                self.min_length_cm,
                self.max_length_cm,
                self.min_weight_kg,
                self.max_weight_kg,
            )
        )


class SpeciesAvailability(_ContentModel):
    seasons: list[str] = Field(default_factory=list)
    time: list[str] = Field(default_factory=list)
    weather_required: list[str] = Field(default_factory=list)
    weather_preferred: list[str] = Field(default_factory=list)
    weather_avoided: list[str] = Field(default_factory=list)


class SpeciesCapture(_ContentModel):
    method: str
    difficulty: int = 1
    behavior: str = "standard"
    hook_tags: list[str] = Field(default_factory=list)
    bait_tags: list[str] = Field(default_factory=list)


class SpeciesEconomy(_ContentModel):
    base_price: Optional[int] = None
    sellable: bool = True


class SpeciesCollection(_ContentModel):
    collectible: bool = True
    group: Optional[str] = None
    recordable: bool = False


class Species(_ContentModel):
    id: int
    key: str
    name: str
    category: str
    environment: str
    assets: SpeciesAssets
    description: str = ""
    biology: SpeciesBiology = Field(default_factory=SpeciesBiology)
    availability: SpeciesAvailability = Field(default_factory=SpeciesAvailability)
    capture: SpeciesCapture
    economy: SpeciesEconomy = Field(default_factory=SpeciesEconomy)
    collection: SpeciesCollection = Field(default_factory=SpeciesCollection)
    rarity: str = "common"
    tags: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class ItemEquipment(_ContentModel):
    equippable: bool = False
    mode: Optional[str] = None
    slot: Optional[str] = None
    capture_method: Optional[str] = None
    tool_profile: Optional[str] = None


class ItemEconomy(_ContentModel):
    buy_price: Optional[int] = None
    sell_price: Optional[int] = None


class ItemInventory(_ContentModel):
    stackable: bool = False
    max_stack: int = 1


class ItemDurability(_ContentModel):
    max: Optional[int] = None
    max_days: Optional[int] = None
    unit: Optional[str] = None
    loss_per_use: Optional[int] = None
    loss_trigger: Optional[str] = None
    repairable: bool = False
    repair_cost: Optional[int] = None


class ItemConsumable(_ContentModel):
    consumed_on_use: bool = False
    consumed_on_attempt: bool = False


class ItemCollection(_ContentModel):
    collectible: bool = False
    group: Optional[str] = None
    numeric: bool = False
    prestige_value: Optional[int] = None


class Item(_ContentModel):
    id: int
    key: str
    name: str
    category: str
    sprite: str
    shadow: Optional[str] = None
    shadow_ready: bool = True
    description: str = ""
    lore: str = ""
    enabled: bool = True
    sources: list[str] = Field(default_factory=list)
    economy: ItemEconomy = Field(default_factory=ItemEconomy)
    inventory: ItemInventory = Field(default_factory=ItemInventory)
    flags: list[str] = Field(default_factory=list)
    equipment: Optional[ItemEquipment] = None
    durability: Optional[ItemDurability] = None
    consumable: Optional[ItemConsumable] = None
    effects: dict[str, Any] = Field(default_factory=dict)
    collection: Optional[ItemCollection] = None


class NpcPortraits(_ContentModel):
    default: str
    alt: Optional[str] = None
    good: Optional[str] = None
    bad: Optional[str] = None


class Npc(_ContentModel):
    id: int
    key: str
    name: Optional[str] = None
    role: Optional[str] = None
    milieu: Optional[str] = None
    shop_mode: Optional[str] = None
    stock: list[str] = Field(default_factory=list)
    enabled: bool = False
    portraits: NpcPortraits
    description: str = ""
    personality: str = ""
    hook: str = ""
    hooks: dict[str, str] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)

    def hook_for(self, time_of_day: str | None = None) -> str:
        """Accroche du moment (dawn/day/dusk/night), sinon `hook`."""
        if time_of_day:
            alt = (self.hooks.get(time_of_day) or "").strip()
            if alt:
                return alt
        return (self.hook or "").strip()

    def portrait_file(self, *, good: bool | None = None) -> str:
        if good is True:
            return self.portraits.good or self.portraits.default
        if good is False:
            return self.portraits.bad or self.portraits.alt or self.portraits.default
        return self.portraits.default


class Milieu(_ContentModel):
    id: Optional[int] = None
    key: str
    name: str
    description: str = ""


class PlayerDefaults(_ContentModel):
    energy_max: int
    energy_start: int
    money_start: int
    energy_regen_per_hour: float = 20
    fish_carry_capacity: int = 5
    non_fish_carry_capacity: int = 5

    @model_validator(mode="after")
    def _check_ranges(self) -> PlayerDefaults:
        if self.energy_max < 1:
            raise ValueError("energy_max doit être ≥ 1")
        if self.energy_start < 0 or self.energy_start > self.energy_max:
            raise ValueError("energy_start doit être entre 0 et energy_max")
        if self.money_start < 0:
            raise ValueError("money_start doit être ≥ 0")
        if self.energy_regen_per_hour < 0:
            raise ValueError("energy_regen_per_hour doit être ≥ 0")
        if self.fish_carry_capacity < 0 or self.non_fish_carry_capacity < 0:
            raise ValueError("capacités de sac doivent être ≥ 0")
        return self


class MoneySettings(_ContentModel):
    bronze_per_silver: int = 100
    silver_per_gold: int = 100

    @model_validator(mode="after")
    def _check_rates(self) -> MoneySettings:
        if self.bronze_per_silver < 1 or self.silver_per_gold < 1:
            raise ValueError("taux monétaires invalides")
        return self


class WeatherKind(_ContentModel):
    key: str
    name: str
    emoji: str = ""


class WorldSettings(_ContentModel):
    timezone: str = "Europe/Paris"
    weather_bucket_minutes: int = 60
    time_windows: dict[str, list[int]] = Field(
        default_factory=lambda: {
            "dawn": [5, 8],
            "day": [8, 18],
            "dusk": [18, 21],
            "night": [21, 5],
        }
    )
    seasons: dict[str, list[int]] = Field(
        default_factory=lambda: {
            "spring": [3, 4, 5],
            "summer": [6, 7, 8],
            "autumn": [9, 10, 11],
            "winter": [12, 1, 2],
        }
    )
    weathers: list[WeatherKind] = Field(
        default_factory=lambda: [
            WeatherKind(key="clear", name="Clair", emoji="☀️"),
            WeatherKind(key="cloudy", name="Nuageux", emoji="☁️"),
            WeatherKind(key="rain", name="Pluie", emoji="🌧️"),
            WeatherKind(key="storm", name="Tempête", emoji="⛈️"),
            WeatherKind(key="fog", name="Brouillard", emoji="🌫️"),
            WeatherKind(key="wind", name="Vent", emoji="🌬️"),
        ]
    )

    @model_validator(mode="after")
    def _check_world(self) -> WorldSettings:
        if self.weather_bucket_minutes < 1:
            raise ValueError("weather_bucket_minutes doit être ≥ 1")
        covered = [m for months in self.seasons.values() for m in months]
        if sorted(covered) != list(range(1, 13)):
            raise ValueError("les saisons doivent couvrir les mois 1–12 sans trou ni doublon")
        if not self.weathers:
            raise ValueError("au moins une météo est requise")
        keys = [w.key for w in self.weathers]
        if len(keys) != len(set(keys)):
            raise ValueError("clés météo dupliquées")
        for key, bounds in self.time_windows.items():
            if len(bounds) != 2:
                raise ValueError(f"fenêtre horaire `{key}` : [début, fin] attendu")
            start, end = bounds
            if not (0 <= start <= 23 and 0 <= end <= 23):
                raise ValueError(f"fenêtre horaire `{key}` hors 0–23")
        return self


class MinigameSettings(_ContentModel):
    rod_wait_min_s: float = 3.5
    rod_wait_max_s: float = 7.0
    rod_window_s: float = 2.0
    net_wait_s: float = 2.0
    net_window_s: float = 10.0

    @model_validator(mode="after")
    def _check_minigame(self) -> MinigameSettings:
        if self.rod_wait_min_s < 0 or self.rod_wait_max_s < self.rod_wait_min_s:
            raise ValueError("délai canne invalide")
        if self.rod_window_s <= 0 or self.net_window_s <= 0:
            raise ValueError("fenêtres mini-jeu doivent être > 0")
        if self.net_wait_s < 0:
            raise ValueError("délai filet invalide")
        return self


class SpecimenSettings(_ContentModel):
    fallback_length_cm: list[float] = Field(default_factory=lambda: [10.0, 50.0])
    fallback_weight_kg: list[float] = Field(default_factory=lambda: [0.08, 2.0])

    @model_validator(mode="after")
    def _check_ranges(self) -> SpecimenSettings:
        for name, pair in (
            ("fallback_length_cm", self.fallback_length_cm),
            ("fallback_weight_kg", self.fallback_weight_kg),
        ):
            if len(pair) != 2:
                raise ValueError(f"{name} : [min, max] attendu")
            if pair[0] <= 0 or pair[1] <= 0 or pair[1] < pair[0]:
                raise ValueError(f"{name} invalide")
        return self


class FishingSettings(_ContentModel):
    cast_energy_cost: int = 8
    rarity_weights: dict[str, float] = Field(
        default_factory=lambda: {"common": 100, "uncommon": 40, "rare": 12}
    )
    weather_preferred_mult: float = 1.25
    weather_avoided_mult: float = 0.5
    minigame: MinigameSettings = Field(default_factory=MinigameSettings)
    specimen: SpecimenSettings = Field(default_factory=SpecimenSettings)
    waste_chance: float = 0.12
    loot_chance: float = 0.06
    night_weight_mult: float = 0.65
    bad_weather_energy_extra: int = 4

    @model_validator(mode="after")
    def _check_fishing(self) -> FishingSettings:
        if self.cast_energy_cost < 0:
            raise ValueError("cast_energy_cost doit être ≥ 0")
        if not self.rarity_weights:
            raise ValueError("rarity_weights ne peut pas être vide")
        for key, value in self.rarity_weights.items():
            if value <= 0:
                raise ValueError(f"poids de rareté `{key}` doit être > 0")
        if self.weather_preferred_mult <= 0 or self.weather_avoided_mult <= 0:
            raise ValueError("multiplicateurs météo doivent être > 0")
        if not (0 <= self.waste_chance <= 1):
            raise ValueError("waste_chance doit être entre 0 et 1")
        if not (0 <= self.loot_chance <= 1):
            raise ValueError("loot_chance doit être entre 0 et 1")
        if self.night_weight_mult <= 0:
            raise ValueError("night_weight_mult doit être > 0")
        if self.bad_weather_energy_extra < 0:
            raise ValueError("bad_weather_energy_extra doit être ≥ 0")
        return self


class BargainSettings(_ContentModel):
    """Remise / prime après une négociation réussie (un tout petit peu)."""

    buy_mult: float = 0.95
    sell_mult: float = 1.05
    waste_mult: float = 1.05
    travel_mult: float = 0.95
    repair_mult: float = 0.95

    @model_validator(mode="after")
    def _small_swing(self) -> BargainSettings:
        if not (0.5 <= self.buy_mult <= 1.0):
            raise ValueError("bargain.buy_mult doit être entre 0,5 et 1")
        if not (1.0 <= self.sell_mult <= 1.5):
            raise ValueError("bargain.sell_mult doit être entre 1 et 1,5")
        if not (1.0 <= self.waste_mult <= 1.5):
            raise ValueError("bargain.waste_mult doit être entre 1 et 1,5")
        if not (0.5 <= self.travel_mult <= 1.0):
            raise ValueError("bargain.travel_mult doit être entre 0,5 et 1")
        if not (0.5 <= self.repair_mult <= 1.0):
            raise ValueError("bargain.repair_mult doit être entre 0,5 et 1")
        return self


class VillageSettings(_ContentModel):
    environment_good_threshold: int = 50
    skull_summon_threshold: int = 10
    travel_cost: int = 20
    travel_minutes: int = 30
    talk_limit: int = 8
    talk_warn_after: int = 5
    bargain: BargainSettings = Field(default_factory=BargainSettings)

    @model_validator(mode="after")
    def _talk_patience(self) -> VillageSettings:
        if self.talk_limit < 1:
            raise ValueError("talk_limit doit être ≥ 1")
        if self.talk_warn_after < 1:
            raise ValueError("talk_warn_after doit être ≥ 1")
        if self.talk_warn_after > self.talk_limit:
            raise ValueError("talk_warn_after doit être ≤ talk_limit")
        return self


class GameSettings(_ContentModel):
    schema_version: int = 1
    player: PlayerDefaults
    money: MoneySettings = Field(default_factory=MoneySettings)
    world: WorldSettings = Field(default_factory=WorldSettings)
    fishing: FishingSettings = Field(default_factory=FishingSettings)
    village: VillageSettings = Field(default_factory=VillageSettings)
