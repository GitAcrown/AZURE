"""Schéma SQLite et ouverture de la base joueur AZURE."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    energy INTEGER NOT NULL,
    energy_max INTEGER NOT NULL,
    money INTEGER NOT NULL,
    milieu_key TEXT,
    created_at TEXT NOT NULL,
    energy_updated_at TEXT,
    energy_bonus_pct REAL NOT NULL DEFAULT 0,
    energy_bonus_until TEXT,
    travel_dest TEXT,
    travel_arrives_at TEXT,
    village_npc_key TEXT,
    village_bucket INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS inventory_stacks (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, item_key),
    CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS gear_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    durability INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipped (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    slot TEXT NOT NULL,
    gear_id INTEGER,
    item_key TEXT,
    PRIMARY KEY (guild_id, user_id, slot),
    FOREIGN KEY (gear_id) REFERENCES gear_instances(id)
);

CREATE INDEX IF NOT EXISTS idx_gear_owner
    ON gear_instances (guild_id, user_id);

CREATE TABLE IF NOT EXISTS fishdex (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    species_key TEXT NOT NULL,
    catch_count INTEGER NOT NULL,
    first_caught_at TEXT NOT NULL,
    best_length_cm REAL,
    best_weight_kg REAL,
    last_length_cm REAL,
    last_weight_kg REAL,
    PRIMARY KEY (guild_id, user_id, species_key),
    CHECK (catch_count > 0)
);

CREATE INDEX IF NOT EXISTS idx_fishdex_owner
    ON fishdex (guild_id, user_id);

CREATE TABLE IF NOT EXISTS guild_records (
    guild_id INTEGER NOT NULL,
    species_key TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    length_cm REAL NOT NULL,
    weight_kg REAL NOT NULL,
    caught_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, species_key, user_id)
);

CREATE TABLE IF NOT EXISTS caught_specimens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    species_key TEXT NOT NULL,
    length_cm REAL NOT NULL,
    weight_kg REAL NOT NULL,
    caught_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_caught_owner
    ON caught_specimens (guild_id, user_id);

CREATE TABLE IF NOT EXISTS guild_state (
    guild_id INTEGER PRIMARY KEY,
    environment_score INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS village_announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    npc_key TEXT NOT NULL,
    text TEXT NOT NULL,
    modifier TEXT,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_village_ann_guild
    ON village_announcements (guild_id, ends_at);

CREATE TABLE IF NOT EXISTS village_talk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    npc_key TEXT NOT NULL,
    question TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL,
    intent TEXT,
    item_key TEXT,
    milieu_key TEXT,
    display TEXT,
    board_keys TEXT,
    quantity INTEGER,
    bucket INTEGER
);

CREATE INDEX IF NOT EXISTS idx_village_talk
    ON village_talk (guild_id, user_id, npc_key, id);
"""

GEAR_SLOTS = frozenset({"tool", "hook", "objet"})
BAIT_SLOT = "bait"
ACTIVE_SLOTS = frozenset({"tool", "hook", "bait", "objet"})

_PLAYER_COLUMN_MIGRATIONS = (
    ("energy_updated_at", "TEXT"),
    ("energy_bonus_pct", "REAL NOT NULL DEFAULT 0"),
    ("energy_bonus_until", "TEXT"),
    ("travel_dest", "TEXT"),
    ("travel_arrives_at", "TEXT"),
    ("village_npc_key", "TEXT"),
    ("village_bucket", "INTEGER"),
)

_VILLAGE_TALK_COLUMN_MIGRATIONS = (
    ("intent", "TEXT"),
    ("item_key", "TEXT"),
    ("milieu_key", "TEXT"),
    ("display", "TEXT"),
    ("board_keys", "TEXT"),
    ("quantity", "INTEGER"),
    ("bucket", "INTEGER"),
)

_FISHDEX_COLUMN_MIGRATIONS = (
    ("best_length_cm", "REAL"),
    ("best_weight_kg", "REAL"),
    ("last_length_cm", "REAL"),
    ("last_weight_kg", "REAL"),
)


async def _migrate_columns(
    conn: aiosqlite.Connection, table: str, columns: tuple[tuple[str, str], ...]
) -> None:
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    if not existing:
        return
    for name, decl in columns:
        if name not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


async def _migrate_players(conn: aiosqlite.Connection) -> None:
    await _migrate_columns(conn, "players", _PLAYER_COLUMN_MIGRATIONS)


async def _guild_records_pk_columns(conn: aiosqlite.Connection) -> list[str]:
    async with conn.execute("PRAGMA table_info(guild_records)") as cur:
        rows = await cur.fetchall()
    keyed = [(int(r[5]), str(r[1])) for r in rows if int(r[5] or 0) > 0]
    keyed.sort()
    return [name for _, name in keyed]


async def _migrate_guild_records(conn: aiosqlite.Connection) -> None:
    pk = await _guild_records_pk_columns(conn)
    if not pk or pk == ["guild_id", "species_key", "user_id"]:
        return
    if pk != ["guild_id", "species_key"]:
        return
    await conn.execute("ALTER TABLE guild_records RENAME TO guild_records_old")
    await conn.execute(
        """
        CREATE TABLE guild_records (
            guild_id INTEGER NOT NULL,
            species_key TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            length_cm REAL NOT NULL,
            weight_kg REAL NOT NULL,
            caught_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, species_key, user_id)
        )
        """
    )
    await conn.execute(
        """
        INSERT INTO guild_records (
            guild_id, species_key, user_id, length_cm, weight_kg, caught_at
        )
        SELECT guild_id, species_key, user_id, length_cm, weight_kg, caught_at
        FROM guild_records_old
        """
    )
    await conn.execute("DROP TABLE guild_records_old")


async def connect_db(path: Path | str) -> aiosqlite.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.executescript(SCHEMA)
    await _migrate_players(conn)
    await _migrate_columns(conn, "fishdex", _FISHDEX_COLUMN_MIGRATIONS)
    await _migrate_columns(conn, "village_talk", _VILLAGE_TALK_COLUMN_MIGRATIONS)
    await _migrate_guild_records(conn)
    await conn.commit()
    return conn
