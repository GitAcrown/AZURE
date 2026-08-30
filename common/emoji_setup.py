"""Upload et liaison des emojis d'application AZURE."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Optional

import discord

from common import emojis as E
from common.asset_emojis import (
    EmojiRegistry,
    MAX_EMOJI_BYTES,
    UI_SPECS,
    iter_emoji_jobs,
    load_registry,
    registry,
    save_registry,
)
from common.catalog import Catalog

logger = logging.getLogger("AZURE.Emojis")

ProgressFn = Callable[[int, int, str], Awaitable[None]]


@dataclass
class UploadReport:
    total: int = 0
    reused: int = 0
    created: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.reused + self.created}/{self.total} liés"]
        if self.created:
            parts.append(f"{self.created} créés")
        if self.reused:
            parts.append(f"{self.reused} déjà présents")
        if self.errors:
            parts.append(f"{len(self.errors)} erreur(s)")
        return " · ".join(parts)


def apply_ui_mapping(mapping: dict[str, str]) -> None:
    for attr, code in mapping.items():
        if hasattr(E, attr) and isinstance(code, str):
            setattr(E, attr, code)


def bind_from_disk() -> EmojiRegistry:
    reg = load_registry()
    apply_ui_mapping(reg.ui)
    return reg


async def bind_application_emojis(bot: discord.Client, catalog: Catalog) -> EmojiRegistry:
    """Réutilise les emojis d'application déjà uploadés. Pas de création."""
    reg = load_registry()
    jobs = iter_emoji_jobs(catalog)
    try:
        existing = {emoji.name: emoji for emoji in await bot.fetch_application_emojis()}
    except discord.HTTPException as exc:
        logger.warning("Impossible de lister les emojis d'application : %s", exc)
        apply_ui_mapping(reg.ui)
        return reg

    changed = False
    for job in jobs:
        emoji = existing.get(job.discord_name)
        if emoji is None:
            continue
        code = str(emoji)
        if reg.get(job.kind, job.key, job.variant) != code:
            reg.set(job, code)
            changed = True

    apply_ui_mapping(reg.ui)
    if changed:
        save_registry(reg)
    bound, total = reg.bound_count(jobs)
    logger.info("Emojis d'application liés : %d/%d", bound, total)
    return reg


async def _create_emoji(bot: discord.Client, name: str, image: bytes) -> discord.Emoji:
    last_exc: discord.HTTPException | None = None
    for _ in range(8):
        try:
            return await bot.create_application_emoji(name=name, image=image)
        except discord.HTTPException as exc:
            last_exc = exc
            if exc.status == 429:
                delay = float(getattr(exc, "retry_after", None) or 2.0)
                await asyncio.sleep(delay + 0.15)
                continue
            raise
    assert last_exc is not None
    raise last_exc


async def setup_application_emojis(
    bot: discord.Client,
    catalog: Catalog,
    *,
    progress: Optional[ProgressFn] = None,
) -> UploadReport:
    """Upload tous les PNG du catalogue manquants comme emojis d'application."""
    reg = load_registry()
    jobs = iter_emoji_jobs(catalog)
    report = UploadReport(total=len(jobs))

    try:
        existing = {emoji.name: emoji for emoji in await bot.fetch_application_emojis()}
    except discord.HTTPException as exc:
        report.errors.append(f"Impossible de lister les emojis d'application : {exc}")
        return report

    for i, job in enumerate(jobs, start=1):
        if progress is not None:
            await progress(i - 1, len(jobs), job.discord_name)
        if not job.path.is_file():
            report.errors.append(f"{job.discord_name} : fichier introuvable `{job.path}`")
            continue
        try:
            if job.discord_name in existing:
                emoji = existing[job.discord_name]
                report.reused += 1
            else:
                image_bytes = job.path.read_bytes()
                if len(image_bytes) > MAX_EMOJI_BYTES:
                    report.errors.append(
                        f"{job.discord_name} : PNG trop lourd ({len(image_bytes)} > {MAX_EMOJI_BYTES})"
                    )
                    continue
                emoji = await _create_emoji(bot, job.discord_name, image_bytes)
                existing[job.discord_name] = emoji
                report.created += 1
                await asyncio.sleep(0.35)
            reg.set(job, str(emoji))
        except discord.HTTPException as exc:
            report.errors.append(f"{job.discord_name} : échec upload — {exc}")
        except OSError as exc:
            report.errors.append(f"{job.discord_name} : lecture impossible — {exc}")

    if progress is not None:
        await progress(len(jobs), len(jobs), "terminé")

    apply_ui_mapping(reg.ui)
    save_registry(reg)
    logger.info("Upload emojis : %s", report.summary())
    return report


def bound_count(catalog: Optional[Catalog] = None) -> tuple[int, int]:
    if catalog is None:
        n = sum(1 for attr, _, _ in UI_SPECS if getattr(E, attr, ""))
        return n, len(UI_SPECS)
    jobs = iter_emoji_jobs(catalog)
    return registry().bound_count(jobs)
