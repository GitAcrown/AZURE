"""Emojis UI AZURE (format <:name:id>).

Remplis automatiquement via `/admin emojis` (emojis d'application).
Tant qu'une valeur est vide, aucun emoji n'est affiché.
"""

from __future__ import annotations


def e(code: str, fallback: str = "") -> str:
    """Renvoie l'emoji custom s'il est renseigné, sinon le fallback (souvent vide)."""
    return code if code else fallback


# --- Économie (coin1 bronze, coin2 argent, coin3 or) ---
COIN1 = ""  # bronze
COIN2 = ""  # argent
COIN3 = ""  # or

# --- Records / médailles ---
MEDAL1 = ""
MEDAL2 = ""
MEDAL3 = ""
MEDAL4 = ""

# --- Navigation (flèches de menus) ---
LEFT = ""
RIGHT = ""
