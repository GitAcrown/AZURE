"""Registre des emojis d'application liés aux assets YAML (sans I/O Discord)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from common.catalog import Catalog, Item

DATA_PATH = Path("assets/UI/emojis_data.json")
_EMOJI_RE = re.compile(r"<a?:\w+:(\d+)>")
MAX_EMOJI_BYTES = 256 * 1024

UI_SPECS: tuple[tuple[str, str, str], ...] = (
    ("COIN1", "coin1.png", "azure_coin1"),
    ("COIN2", "coin2.png", "azure_coin2"),
    ("COIN3", "coin3.png", "azure_coin3"),
    ("MEDAL1", "medal1.png", "azure_medal1"),
    ("MEDAL2", "medal2.png", "azure_medal2"),
    ("MEDAL3", "medal3.png", "azure_medal3"),
    ("MEDAL4", "medal4.png", "azure_medal4"),
    ("LEFT", "left.png", "azure_left"),
    ("RIGHT", "right.png", "azure_right"),
)


@dataclass(frozen=True)
class AssetEmojiJob:
    kind: str
    key: str
    variant: str
    discord_name: str
    path: Path


@dataclass
class EmojiRegistry:
    ui: dict[str, str] = field(default_factory=dict)
    species: dict[str, dict[str, str]] = field(default_factory=dict)
    items: dict[str, dict[str, str]] = field(default_factory=dict)
    npcs: dict[str, dict[str, str]] = field(default_factory=dict)

    def set(self, job: AssetEmojiJob, code: str) -> None:
        if job.kind == "ui":
            self.ui[job.key] = code
            return
        bucket = getattr(self, job.kind)
        bucket.setdefault(job.key, {})[job.variant] = code

    def get(self, kind: str, key: str, variant: str) -> str:
        if kind == "ui":
            return self.ui.get(key, "")
        return getattr(self, kind).get(key, {}).get(variant, "")

    def bound_count(self, jobs: list[AssetEmojiJob]) -> tuple[int, int]:
        n = sum(1 for job in jobs if self.get(job.kind, job.key, job.variant))
        return n, len(jobs)

    def to_json(self) -> dict[str, Any]:
        return {
            "ui": dict(self.ui),
            "species": {k: dict(v) for k, v in self.species.items()},
            "items": {k: dict(v) for k, v in self.items.items()},
            "npcs": {k: dict(v) for k, v in self.npcs.items()},
        }


_registry = EmojiRegistry()


def registry() -> EmojiRegistry:
    return _registry


def item_is_collectible(item: Item) -> bool:
    if item.collection is not None and item.collection.collectible:
        return True
    return item.category in {"treasure", "collectible", "fossil", "summon_currency"}


def _discord_name(filename: str) -> str:
    stem = Path(filename).stem
    name = re.sub(r"[^a-zA-Z0-9_]", "_", stem)
    if len(name) < 2:
        name = f"az_{name}"
    return name[:32]


def iter_emoji_jobs(catalog: Catalog) -> list[AssetEmojiJob]:
    root = catalog.assets_root
    jobs: list[AssetEmojiJob] = []
    for attr, filename, discord_name in UI_SPECS:
        jobs.append(
            AssetEmojiJob("ui", attr, "", discord_name, root / "UI" / filename)
        )
    for spec in catalog.species:
        jobs.append(
            AssetEmojiJob(
                "species",
                spec.key,
                "sprite",
                _discord_name(spec.assets.sprite),
                root / "species" / spec.assets.sprite,
            )
        )
        jobs.append(
            AssetEmojiJob(
                "species",
                spec.key,
                "shadow",
                _discord_name(spec.assets.shadow),
                root / "species" / spec.assets.shadow,
            )
        )
    for item in catalog.items:
        jobs.append(
            AssetEmojiJob(
                "items",
                item.key,
                "sprite",
                _discord_name(item.sprite),
                root / "items" / item.sprite,
            )
        )
        if item_is_collectible(item) and item.shadow:
            jobs.append(
                AssetEmojiJob(
                    "items",
                    item.key,
                    "shadow",
                    _discord_name(item.shadow),
                    root / "items" / item.shadow,
                )
            )
    for npc in catalog.npcs:
        jobs.append(
            AssetEmojiJob(
                "npcs",
                npc.key,
                "default",
                _discord_name(npc.portraits.default),
                root / "npcs" / npc.portraits.default,
            )
        )
        if npc.portraits.alt:
            jobs.append(
                AssetEmojiJob(
                    "npcs",
                    npc.key,
                    "alt",
                    _discord_name(npc.portraits.alt),
                    root / "npcs" / npc.portraits.alt,
                )
            )
    return jobs


def load_registry() -> EmojiRegistry:
    global _registry
    reg = EmojiRegistry()
    if not DATA_PATH.is_file():
        _registry = reg
        return reg
    with DATA_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        _registry = reg
        return reg
    if "ui" not in raw and any(k.startswith("COIN") or k.startswith("MEDAL") for k in raw):
        reg.ui = {k: v for k, v in raw.items() if isinstance(v, str)}
    else:
        ui = raw.get("ui") or {}
        if isinstance(ui, dict):
            reg.ui = {k: v for k, v in ui.items() if isinstance(v, str)}
        for bucket in ("species", "items", "npcs"):
            block = raw.get(bucket) or {}
            if not isinstance(block, dict):
                continue
            target: dict[str, dict[str, str]] = {}
            for key, variants in block.items():
                if not isinstance(variants, dict):
                    continue
                target[str(key)] = {str(vk): vv for vk, vv in variants.items() if isinstance(vv, str)}
            setattr(reg, bucket, target)
    _registry = reg
    return reg


def save_registry(reg: Optional[EmojiRegistry] = None) -> None:
    current = reg or _registry
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(current.to_json(), f, ensure_ascii=False, indent=4)
        f.write("\n")


def species_emoji(key: str, *, shadow: bool = False) -> str:
    return _registry.get("species", key, "shadow" if shadow else "sprite")


def ui_emoji(key: str) -> str:
    return _registry.ui.get(key, "")


def item_emoji(key: str, *, shadow: bool = False) -> str:
    return _registry.get("items", key, "shadow" if shadow else "sprite")


def npc_emoji(key: str, *, alt: bool = False) -> str:
    return _registry.get("npcs", key, "alt" if alt else "default")


def with_emoji(code: str, text: str) -> str:
    code = (code or "").strip()
    return f"{code} {text}" if code else text


GALLERY_PAGE_SIZE = 32

_GALLERY_LABELS = {
    ("ui", ""): "UI",
    ("species", "sprite"): "Espèces",
    ("species", "shadow"): "Espèces · ombre",
    ("items", "sprite"): "Items",
    ("items", "shadow"): "Items · ombre",
    ("npcs", "default"): "PNJ",
    ("npcs", "alt"): "PNJ · alt",
}


def gallery_label(job: AssetEmojiJob) -> str:
    return _GALLERY_LABELS.get((job.kind, job.variant), job.kind)


def gallery_sections(catalog: Catalog) -> list[tuple[str, list[str]]]:
    """Emojis liés, groupés dans l'ordre des jobs (UI, espèces, items, PNJ)."""
    sections: list[tuple[str, list[str]]] = []
    current_label = ""
    current_codes: list[str] = []
    for job in iter_emoji_jobs(catalog):
        code = (_registry.get(job.kind, job.key, job.variant) or "").strip()
        if not code:
            continue
        label = gallery_label(job)
        if label != current_label:
            if current_codes:
                sections.append((current_label, current_codes))
            current_label = label
            current_codes = [code]
        else:
            current_codes.append(code)
    if current_codes:
        sections.append((current_label, current_codes))
    return sections


def paginate_gallery(
    sections: list[tuple[str, list[str]]],
    *,
    page_size: int = GALLERY_PAGE_SIZE,
) -> list[list[tuple[str, list[str]]]]:
    """Découpe les sections en pages d'au plus `page_size` emojis."""
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    pages: list[list[tuple[str, list[str]]]] = []
    current: list[tuple[str, list[str]]] = []
    count = 0
    for title, codes in sections:
        offset = 0
        while offset < len(codes):
            room = page_size - count
            if room <= 0:
                pages.append(current)
                current = []
                count = 0
                room = page_size
            chunk = codes[offset : offset + room]
            heading = title if offset == 0 else f"{title} (suite)"
            current.append((heading, chunk))
            count += len(chunk)
            offset += len(chunk)
    if current:
        pages.append(current)
    return pages


def emoji_cdn_url(emoji_str: str, *, size: int = 256) -> Optional[str]:
    m = _EMOJI_RE.fullmatch((emoji_str or "").strip())
    if not m:
        return None
    return f"https://cdn.discordapp.com/emojis/{m.group(1)}.png?size={size}&quality=lossless"


def asset_file(path: Path, *, filename: Optional[str] = None, preload: bool = False):
    """`discord.File` local pour thumbnail LayoutView, ou None."""
    if not path.is_file():
        return None
    import io

    import discord

    name = filename or path.name
    if preload:
        return discord.File(io.BytesIO(path.read_bytes()), filename=name)
    return discord.File(path, filename=name)
