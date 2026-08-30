"""Catalogue de contenu AZURE (YAML → modèles)."""

from .errors import CatalogError
from .loader import Catalog, load_catalog
from .models import (
    FishingSettings,
    GameSettings,
    Item,
    Milieu,
    Npc,
    Species,
    VillageSettings,
    WorldSettings,
)

__all__ = [
    "Catalog",
    "CatalogError",
    "FishingSettings",
    "GameSettings",
    "Item",
    "Milieu",
    "Npc",
    "Species",
    "VillageSettings",
    "WorldSettings",
    "load_catalog",
]
