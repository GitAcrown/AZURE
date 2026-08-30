"""Génération de spécimen (taille / poids), seedable."""

from __future__ import annotations

import random
from dataclasses import dataclass

from common.catalog import Species
from common.catalog.models import SpecimenSettings


@dataclass(frozen=True)
class Specimen:
    length_cm: float
    weight_kg: float


def _pair(lo: float, hi: float) -> tuple[float, float]:
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def generate_specimen(
    species: Species,
    settings: SpecimenSettings,
    rng: random.Random,
    *,
    beat: Specimen | None = None,
) -> Specimen:
    bio = species.biology
    if bio.min_length_cm is not None and bio.max_length_cm is not None:
        length_lo, length_hi = _pair(float(bio.min_length_cm), float(bio.max_length_cm))
    else:
        length_lo, length_hi = _pair(*settings.fallback_length_cm)
    length = rng.uniform(length_lo, length_hi)

    if bio.min_weight_kg is not None and bio.max_weight_kg is not None:
        weight_lo, weight_hi = _pair(float(bio.min_weight_kg), float(bio.max_weight_kg))
    else:
        weight_lo, weight_hi = _pair(*settings.fallback_weight_kg)
    span = length_hi - length_lo
    t = 0.5 if span <= 0 else (length - length_lo) / span
    t = min(1.0, max(0.0, t + rng.uniform(-0.08, 0.08)))
    weight = weight_lo + t * (weight_hi - weight_lo)
    spec = Specimen(length_cm=round(length, 1), weight_kg=round(weight, 3))
    if beat is None:
        return spec
    beats = spec.length_cm > beat.length_cm or (
        spec.length_cm == beat.length_cm and spec.weight_kg > beat.weight_kg
    )
    if beats:
        return spec
    forced_len = round(length_hi, 1)
    forced_w = round(weight_hi, 3)
    if forced_len > beat.length_cm or (
        forced_len == beat.length_cm and forced_w > beat.weight_kg
    ):
        return Specimen(length_cm=forced_len, weight_kg=forced_w)
    return spec
