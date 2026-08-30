"""Erreurs du store joueur AZURE."""

from __future__ import annotations


class PlayerError(Exception):
    """Opération joueur invalide (item inconnu, quantité, slot, etc.)."""
