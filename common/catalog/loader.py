"""Chargement et validation du contenu YAML AZURE."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional, Union

import yaml
from pydantic import ValidationError

from .errors import CatalogError
from .models import GameSettings, Item, Milieu, Npc, Species

logger = logging.getLogger("AZURE.Catalog")

KeyOrId = Union[str, int]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CatalogError(f"fichier introuvable : {path}", path=path)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise CatalogError(f"YAML illisible : {exc}", path=path) from exc
    if not isinstance(data, dict):
        raise CatalogError("la racine du YAML doit être un mapping", path=path)
    return data


def _as_list(raw: Any, *, path: Path, field: str) -> list[dict[str, Any]]:
    value = raw.get(field)
    if not isinstance(value, list):
        raise CatalogError(f"champ `{field}` manquant ou invalide (liste attendue)", path=path)
    entries: list[dict[str, Any]] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise CatalogError(f"`{field}[{i}]` doit être un mapping", path=path)
        entries.append(item)
    return entries


def _require_file(directory: Path, filename: str, *, path: Path, entry_id: int | None, key: str) -> Optional[str]:
    loc = f"{path} · id={entry_id} · key={key}" if entry_id is not None else f"{path} · key={key}"
    if not filename:
        return f"{loc} — nom de fichier vide"
    target = directory / filename
    if not target.is_file():
        return f"{loc} — asset manquant : {target.name}"
    return None


def _index_unique(entries: Iterable[Any], *, kind: str, path: Path) -> tuple[dict[int, Any], dict[str, Any], list[str]]:
    by_id: dict[int, Any] = {}
    by_key: dict[str, Any] = {}
    errors: list[str] = []
    for entry in entries:
        if entry.id in by_id:
            errors.append(f"{path} · id={entry.id} · key={entry.key} — {kind} id dupliqué")
        else:
            by_id[entry.id] = entry
        if entry.key in by_key:
            errors.append(f"{path} · id={entry.id} · key={entry.key} — {kind} key dupliquée")
        else:
            by_key[entry.key] = entry
    return by_id, by_key, errors


def _parse_entries(cls, raw_list: list[dict[str, Any]], *, path: Path, kind: str) -> tuple[list[Any], list[str]]:
    parsed: list[Any] = []
    errors: list[str] = []
    for i, raw in enumerate(raw_list):
        try:
            parsed.append(cls.model_validate(raw))
        except ValidationError as exc:
            ident = raw.get("key") or raw.get("id") or i
            errors.append(f"{path} · {kind} `{ident}` — {exc.error_count()} erreur(s) de schéma")
            for err in exc.errors()[:8]:
                loc = ".".join(str(part) for part in err.get("loc", ()))
                errors.append(f"    {loc}: {err.get('msg')}")
    return parsed, errors


class Catalog:
    """Accès au contenu fixe (espèces, items, milieux, PNJ)."""

    def __init__(
        self,
        *,
        assets_root: Path,
        species: list[Species],
        items: list[Item],
        milieus: list[Milieu],
        npcs: list[Npc],
        game: GameSettings,
        schema_versions: dict[str, Any] | None = None,
    ) -> None:
        self.assets_root = assets_root
        self.schema_versions = schema_versions or {}
        self.game = game

        self._species_by_id = {s.id: s for s in species}
        self._species_by_key = {s.key: s for s in species}
        self._items_by_id = {it.id: it for it in items}
        self._items_by_key = {it.key: it for it in items}
        self._milieus_by_id = {m.id: m for m in milieus if m.id is not None}
        self._milieus_by_key = {m.key: m for m in milieus}
        self._npcs_by_id = {n.id: n for n in npcs}
        self._npcs_by_key = {n.key: n for n in npcs}

        self.species = list(species)
        self.items = list(items)
        self.milieus = list(milieus)
        self.npcs = list(npcs)

    def summary(self) -> str:
        enabled_items = sum(1 for it in self.items if it.enabled)
        return (
            f"{len(self.species)} espèces, {len(self.items)} items "
            f"({enabled_items} actifs), {len(self.milieus)} milieux, {len(self.npcs)} pnjs"
        )

    def get_species(self, key_or_id: KeyOrId) -> Species:
        return self._lookup(key_or_id, self._species_by_id, self._species_by_key, "espèce")

    def get_item(self, key_or_id: KeyOrId) -> Item:
        return self._lookup(key_or_id, self._items_by_id, self._items_by_key, "item")

    def get_npc(self, key_or_id: KeyOrId) -> Npc:
        return self._lookup(key_or_id, self._npcs_by_id, self._npcs_by_key, "pnj")

    def get_milieu(self, key_or_id: KeyOrId) -> Milieu:
        return self._lookup(key_or_id, self._milieus_by_id, self._milieus_by_key, "milieu")

    def species_in(self, environment: str, method: Optional[str] = None) -> list[Species]:
        out = [s for s in self.species if s.environment == environment]
        if method is not None:
            out = [s for s in out if s.capture.method == method]
        return out

    def items_by_category(self, category: str, *, enabled_only: bool = False) -> list[Item]:
        return [
            it
            for it in self.items
            if it.category == category and (not enabled_only or it.enabled)
        ]

    def items_by_slot(self, slot: str, *, enabled_only: bool = False) -> list[Item]:
        return [
            it
            for it in self.items
            if it.equipment is not None
            and it.equipment.slot == slot
            and (not enabled_only or it.enabled)
        ]

    def items_by_source(self, source: str, *, enabled_only: bool = False) -> list[Item]:
        return [
            it
            for it in self.items
            if source in it.sources and (not enabled_only or it.enabled)
        ]

    def npcs_by_role(self, role: str, *, enabled_only: bool = True) -> list[Npc]:
        return [
            n
            for n in self.npcs
            if n.role == role and (not enabled_only or n.enabled)
        ]

    def npcs_by_shop_mode(self, mode: str, *, enabled_only: bool = True) -> list[Npc]:
        return [
            n
            for n in self.npcs_by_role("shop", enabled_only=enabled_only)
            if n.shop_mode == mode
        ]

    def _lookup(
        self,
        key_or_id: KeyOrId,
        by_id: dict[int, Any],
        by_key: dict[str, Any],
        kind: str,
    ) -> Any:
        if isinstance(key_or_id, int):
            obj = by_id.get(key_or_id)
        else:
            obj = by_key.get(key_or_id)
            if obj is None and key_or_id.isdigit():
                obj = by_id.get(int(key_or_id))
        if obj is None:
            raise CatalogError(f"{kind} introuvable : {key_or_id!r}")
        return obj


def load_catalog(assets_root: Path | str = Path("assets")) -> Catalog:
    """Charge et valide tout le contenu fixe. Lève CatalogError si invalide."""
    root = Path(assets_root)
    errors: list[str] = []

    milieus_path = root / "milieus" / "milieus.yaml"
    species_path = root / "species" / "species.yaml"
    items_path = root / "items" / "items.yaml"
    npcs_path = root / "npcs" / "npcs.yaml"
    game_path = root / "game.yaml"

    milieus_raw = _load_yaml(milieus_path)
    species_raw = _load_yaml(species_path)
    items_raw = _load_yaml(items_path)
    npcs_raw = _load_yaml(npcs_path)
    game_raw = _load_yaml(game_path)

    milieus, milieu_errs = _parse_entries(
        Milieu, _as_list(milieus_raw, path=milieus_path, field="milieus"), path=milieus_path, kind="milieu"
    )
    species, species_errs = _parse_entries(
        Species, _as_list(species_raw, path=species_path, field="species"), path=species_path, kind="espèce"
    )
    items, item_errs = _parse_entries(
        Item, _as_list(items_raw, path=items_path, field="items"), path=items_path, kind="item"
    )
    npcs, npc_errs = _parse_entries(
        Npc, _as_list(npcs_raw, path=npcs_path, field="npcs"), path=npcs_path, kind="pnj"
    )
    errors.extend(milieu_errs + species_errs + item_errs + npc_errs)

    game: GameSettings | None = None
    try:
        game = GameSettings.model_validate(game_raw)
    except ValidationError as exc:
        errors.append(f"{game_path} — {exc.error_count()} erreur(s) de schéma")
        for err in exc.errors()[:8]:
            loc = ".".join(str(part) for part in err.get("loc", ()))
            errors.append(f"    {loc}: {err.get('msg')}")

    _, _, dup_m = _index_unique(milieus, kind="milieu", path=milieus_path)
    _, _, dup_s = _index_unique(species, kind="espèce", path=species_path)
    _, _, dup_i = _index_unique(items, kind="item", path=items_path)
    _, _, dup_n = _index_unique(npcs, kind="pnj", path=npcs_path)
    errors.extend(dup_m + dup_s + dup_i + dup_n)

    milieu_keys = {m.key for m in milieus}
    item_keys = {it.key for it in items}
    species_dir = species_path.parent
    items_dir = items_path.parent
    npcs_dir = npcs_path.parent

    for spec in species:
        if spec.environment not in milieu_keys:
            errors.append(
                f"{species_path} · id={spec.id} · key={spec.key} — "
                f"milieu inconnu : {spec.environment!r}"
            )
        err = _require_file(
            species_dir, spec.assets.sprite, path=species_path, entry_id=spec.id, key=spec.key
        )
        if err:
            errors.append(err)
        err = _require_file(
            species_dir, spec.assets.shadow, path=species_path, entry_id=spec.id, key=spec.key
        )
        if err:
            errors.append(err)

    for item in items:
        err = _require_file(items_dir, item.sprite, path=items_path, entry_id=item.id, key=item.key)
        if err:
            errors.append(err)
        if item.shadow_ready:
            if not item.shadow:
                errors.append(
                    f"{items_path} · id={item.id} · key={item.key} — shadow requis (shadow_ready=true)"
                )
            else:
                err = _require_file(
                    items_dir, item.shadow, path=items_path, entry_id=item.id, key=item.key
                )
                if err:
                    errors.append(err)

    for npc in npcs:
        err = _require_file(
            npcs_dir, npc.portraits.default, path=npcs_path, entry_id=npc.id, key=npc.key
        )
        if err:
            errors.append(err)
        for extra in (npc.portraits.alt, npc.portraits.good, npc.portraits.bad):
            if extra:
                err = _require_file(
                    npcs_dir, extra, path=npcs_path, entry_id=npc.id, key=npc.key
                )
                if err:
                    errors.append(err)
        if npc.enabled and npc.role == "shop":
            if npc.shop_mode not in {"sell", "buy"}:
                errors.append(
                    f"{npcs_path} · id={npc.id} · key={npc.key} — shop_mode `sell` ou `buy` requis"
                )
            if npc.shop_mode == "sell" and not npc.stock:
                errors.append(
                    f"{npcs_path} · id={npc.id} · key={npc.key} — stock requis pour un vendeur"
                )
            for item_key in npc.stock:
                if item_key not in item_keys:
                    errors.append(
                        f"{npcs_path} · id={npc.id} · key={npc.key} — "
                        f"item de stock inconnu : {item_key!r}"
                    )

    if errors:
        raise CatalogError(errors)
    if game is None:
        raise CatalogError("game.yaml invalide", path=game_path)

    catalog = Catalog(
        assets_root=root,
        species=species,
        items=items,
        milieus=milieus,
        npcs=npcs,
        game=game,
        schema_versions={
            "species": species_raw.get("schema_version"),
            "items": items_raw.get("schema_version"),
            "milieus": milieus_raw.get("schema_version"),
            "npcs": npcs_raw.get("schema_version"),
            "game": game_raw.get("schema_version"),
        },
    )

    bio_incomplete = sum(1 for s in species if s.biology.is_incomplete())
    empty_tags = sum(1 for s in species if not s.tags)
    if bio_incomplete:
        logger.warning("%d espèce(s) avec biology incomplet", bio_incomplete)
    if empty_tags:
        logger.warning("%d espèce(s) avec tags vides", empty_tags)

    disabled = [it.key for it in items if not it.enabled]
    if disabled:
        logger.info("Items désactivés (%d) : %s", len(disabled), ", ".join(disabled))

    by_env = defaultdict(int)
    for s in species:
        by_env[s.environment] += 1
    logger.info("Catalogue chargé : %s", catalog.summary())
    logger.info("Espèces par milieu : %s", ", ".join(f"{k}={v}" for k, v in sorted(by_env.items())))
    return catalog
