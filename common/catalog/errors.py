"""Erreurs du catalogue de contenu AZURE."""

from __future__ import annotations

from pathlib import Path


class CatalogError(Exception):
    """Donnée de contenu invalide (YAML, asset, identifiant)."""

    def __init__(
        self,
        errors: str | list[str],
        *,
        path: Path | str | None = None,
        entry_id: int | None = None,
        key: str | None = None,
    ) -> None:
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        self.path = Path(path) if path is not None else None
        self.entry_id = entry_id
        self.key = key

        lines: list[str] = []
        for msg in self.errors:
            loc = _format_loc(self.path, entry_id, key)
            lines.append(f"{loc} — {msg}" if loc else msg)
        super().__init__("Catalogue invalide :\n" + "\n".join(f"• {line}" for line in lines))


def _format_loc(path: Path | None, entry_id: int | None, key: str | None) -> str:
    parts: list[str] = []
    if path is not None:
        parts.append(str(path).replace("\\", "/"))
    if entry_id is not None:
        parts.append(f"id={entry_id}")
    if key:
        parts.append(f"key={key}")
    return " · ".join(parts)
