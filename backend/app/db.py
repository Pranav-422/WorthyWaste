"""Storage. SQLite for local development and tests; Postgres (DATABASE_URL, e.g. Neon on Vercel) in
deployment. Both run the same SQL: queries are written with `?` placeholders and portable SQL, and
`Database` adapts them for Postgres."""
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("WW_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("WW_DB", DATA_DIR / "worthywaste.db"))
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")

# Tables in dependency order (referenced tables first). Used for schema, wipe and copy.
TABLES = ["groups", "collectors", "dealers", "materials", "sale_requests", "photos", "payments",
          "upi_events", "recycler_sales", "batches", "transactions", "scores", "loans", "fraud_flags",
          "messages"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  leader_id  INTEGER,
  city       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collectors (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  phone          TEXT NOT NULL UNIQUE,
  pin_hash       TEXT,               -- PBKDF2, see auth.py
  language       TEXT NOT NULL DEFAULT 'hi',
  id_type        TEXT,
  id_ref_hash    TEXT,               -- salted hash, never the raw ID
  group_id       INTEGER REFERENCES groups(id),
  group_guarantee INTEGER NOT NULL DEFAULT 0,
  qr_token       TEXT NOT NULL UNIQUE,
  upi_vpa        TEXT,
  basic_phone    INTEGER NOT NULL DEFAULT 0,
  equipment      TEXT NOT NULL DEFAULT 'hand_cart',
  credits        INTEGER NOT NULL DEFAULT 0,
  consent_at     TEXT,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dealers (
  id          INTEGER PRIMARY KEY,
  shop_name   TEXT NOT NULL,
  owner_name  TEXT NOT NULL,
  phone       TEXT NOT NULL UNIQUE,
  pin_hash    TEXT,
  lat         REAL NOT NULL,
  lng         REAL NOT NULL,
  scale_id    TEXT,
  upi_vpa     TEXT,
  reputation  INTEGER NOT NULL DEFAULT 80,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
  code         TEXT PRIMARY KEY,
  sort_order   INTEGER NOT NULL,
  label_en     TEXT NOT NULL,
  label_hi     TEXT NOT NULL,
  rate_per_kg  REAL NOT NULL,
  co2e_per_kg  REAL               -- only set where we can defend the factor (PET)
);

CREATE TABLE IF NOT EXISTS sale_requests (
  id            INTEGER PRIMARY KEY,
  collector_id  INTEGER NOT NULL REFERENCES collectors(id),
  dealer_id     INTEGER REFERENCES dealers(id),
  material      TEXT NOT NULL REFERENCES materials(code),
  est_kg        REAL NOT NULL,
  photo_url     TEXT,
  photo_phash   TEXT,
  lat           REAL,
  lng           REAL,
  channel       TEXT NOT NULL DEFAULT 'app',     -- app | ivr
  status        TEXT NOT NULL DEFAULT 'open',
    -- open, accepted, weighed, paying, completed, expired, rejected, awaiting_ivr
  dealer_lat    REAL,
  dealer_lng    REAL,
  gps_distance_m REAL,
  scale_kg      REAL,
  scale_source  TEXT,
  reject_reason TEXT,
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL
);

-- Photos live in the database so every serverless instance can serve them.
CREATE TABLE IF NOT EXISTS photos (
  name       TEXT PRIMARY KEY,
  data       BLOB NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
  id           INTEGER PRIMARY KEY,
  request_id   INTEGER NOT NULL REFERENCES sale_requests(id),
  amount       REAL NOT NULL,
  payer_vpa    TEXT NOT NULL,
  payee_vpa    TEXT NOT NULL,
  provider_ref TEXT NOT NULL UNIQUE,
  status       TEXT NOT NULL DEFAULT 'pending',   -- pending, success, failed
  created_at   TEXT NOT NULL
);

-- Every UPI movement the aggregator reports between platform VPAs, both directions.
-- Basis for the circular-payment rule.
CREATE TABLE IF NOT EXISTS upi_events (
  id         INTEGER PRIMARY KEY,
  from_vpa   TEXT NOT NULL,
  to_vpa     TEXT NOT NULL,
  amount     REAL NOT NULL,
  upi_ref    TEXT NOT NULL,
  at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recycler_sales (
  id            INTEGER PRIMARY KEY,
  dealer_id     INTEGER NOT NULL REFERENCES dealers(id),
  recycler_name TEXT NOT NULL,
  material      TEXT NOT NULL,
  kg            REAL NOT NULL,
  invoice_ref   TEXT NOT NULL,
  sold_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
  id               INTEGER PRIMARY KEY,
  code             TEXT NOT NULL UNIQUE,
  dealer_id        INTEGER NOT NULL REFERENCES dealers(id),
  material         TEXT NOT NULL,
  total_kg         REAL NOT NULL DEFAULT 0,
  recycler_sale_id INTEGER REFERENCES recycler_sales(id),
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
  id           INTEGER PRIMARY KEY,
  request_id   INTEGER NOT NULL UNIQUE REFERENCES sale_requests(id),
  collector_id INTEGER NOT NULL REFERENCES collectors(id),
  dealer_id    INTEGER NOT NULL REFERENCES dealers(id),
  material     TEXT NOT NULL,
  est_kg       REAL NOT NULL,
  scale_kg     REAL NOT NULL,
  rate_per_kg  REAL NOT NULL,
  amount       REAL NOT NULL,
  upi_ref      TEXT NOT NULL,
  dealer_lat   REAL,
  dealer_lng   REAL,
  credits      INTEGER NOT NULL,
  batch_id     INTEGER REFERENCES batches(id),
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
  collector_id INTEGER PRIMARY KEY REFERENCES collectors(id),
  score        INTEGER NOT NULL,
  inputs_json  TEXT NOT NULL,
  computed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loans (
  id             INTEGER PRIMARY KEY,
  collector_id   INTEGER NOT NULL REFERENCES collectors(id),
  group_id       INTEGER REFERENCES groups(id),
  principal      REAL NOT NULL,
  tenure_m       INTEGER NOT NULL,
  status         TEXT NOT NULL,            -- active, repaid, defaulted
  instalments_due     INTEGER NOT NULL DEFAULT 0,
  instalments_on_time INTEGER NOT NULL DEFAULT 0,
  disbursed_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fraud_flags (
  id          INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL,             -- collector, dealer, request, transaction
  entity_id   INTEGER NOT NULL,
  rule        TEXT NOT NULL,
  detail      TEXT NOT NULL,
  evidence_json TEXT,
  collector_id INTEGER REFERENCES collectors(id),
  dealer_id    INTEGER REFERENCES dealers(id),
  status      TEXT NOT NULL DEFAULT 'open',   -- open, confirmed, dismissed
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY,
  collector_id INTEGER NOT NULL REFERENCES collectors(id),
  channel      TEXT NOT NULL,             -- voice, whatsapp, ivr
  language     TEXT NOT NULL,
  text         TEXT NOT NULL,
  meta_json    TEXT,                      -- structured fields, so the app can voice any amount
  created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_collector ON transactions(collector_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tx_dealer ON transactions(dealer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_req_status ON sale_requests(status);
CREATE INDEX IF NOT EXISTS idx_upi_from ON upi_events(from_vpa, at);
"""

# Columns added after the first release; created on older databases at startup.
MIGRATIONS = [
    ("messages", "meta_json", "TEXT"),
    ("collectors", "pin_hash", "TEXT"),
    ("dealers", "pin_hash", "TEXT"),
    ("materials", "sort_order", "INTEGER"),
]

MATERIALS = [
    # code, order, English, Hindi, ₹/kg, kg CO2e avoided per kg (PET only, per Design Doc)
    ("plastic", 1, "Plastic bottles", "प्लास्टिक बोतल", 12.4, 1.5),
    ("cardboard", 2, "Cardboard", "गत्ता", 9.0, None),
    ("metal", 3, "Cans & tin", "डिब्बे / टिन", 28.0, None),
    ("paper", 4, "Newspaper", "अखबार", 11.0, None),
    ("wire", 5, "Wire", "तार", 45.0, None),
    ("glass", 6, "Glass", "कांच", 2.0, None),
]


def _pg_schema(sql: str) -> str:
    # Surrogate keys become identity columns; REAL is float4 in Postgres, so widen it.
    sql = re.sub(r"\bid(\s+)INTEGER PRIMARY KEY", r"id\1BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", sql)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)
    return sql.replace("BLOB", "BYTEA")


class Row:
    """Postgres row that behaves like sqlite3.Row: index by name or position, iterate/unpack over
    values, and dict(row) gives {column: value}. Unlike a dict, repeated column names don't collapse."""

    __slots__ = ("_names", "_values", "_index")

    def __init__(self, names: list[str], values):
        self._names = names
        self._values = tuple(values)
        self._index = {n: i for i, n in enumerate(names)}

    def keys(self):
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"Row({dict(zip(self._names, self._values))!r})"


class Cursor:
    def __init__(self, rows: list, lastrowid=None, rowcount: int = -1):
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
_ID_TABLES = {"groups", "collectors", "dealers", "sale_requests", "payments", "upi_events", "recycler_sales",
              "batches", "transactions", "loans", "fraud_flags", "messages"}


class Database:
    """Thin wrapper giving SQLite and Postgres the same execute()/cursor interface."""

    def __init__(self, url: str | None = None, path: str | Path | None = None):
        self.is_pg = bool(url)
        self._url = url
        self._path = path
        self._conn = None
        self._connect()

    # ----- connection -----

    def _connect(self):
        if self.is_pg:
            import psycopg
            from psycopg.types.numeric import FloatLoader

            self._conn = psycopg.connect(self._url, autocommit=True, prepare_threshold=None)
            # SUM() over integers comes back as numeric; keep everything float/int like SQLite does.
            self._conn.adapters.register_loader("numeric", FloatLoader)
        else:
            if str(self._path) != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            if str(self._path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")

    def ensure_alive(self):
        """Serverless instances sit idle; Postgres may drop the connection in between."""
        if self.is_pg and (self._conn is None or self._conn.closed or self._conn.broken):
            self._connect()

    # ----- queries -----

    def execute(self, sql: str, params=()) -> Cursor:
        if not self.is_pg:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            return Cursor(rows, cur.lastrowid, cur.rowcount)

        pg_sql = sql.replace("%", "%%").replace("?", "%s")
        m = _INSERT_TABLE.match(sql)
        wants_id = bool(m and m.group(1).lower() in _ID_TABLES and "RETURNING" not in sql.upper())
        if wants_id:
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
        with self._conn.cursor() as cur:
            cur.execute(pg_sql, tuple(params))
            if cur.description:
                names = [d.name for d in cur.description]
                rows = [Row(names, r) for r in cur.fetchall()]
            else:
                rows = []
            lastrowid = rows[-1]["id"] if wants_id and rows else None
            return Cursor(rows, lastrowid, cur.rowcount)

    def executemany(self, sql: str, seq) -> None:
        if not self.is_pg:
            self._conn.executemany(sql, seq)
            return
        with self._conn.cursor() as cur:
            cur.executemany(sql.replace("%", "%%").replace("?", "%s"), [tuple(p) for p in seq])

    def executescript(self, sql: str) -> None:
        if not self.is_pg:
            self._conn.executescript(sql)
            return
        for stmt in [s.strip() for s in sql.split(";")]:
            if stmt and not all(line.strip().startswith("--") or not line.strip() for line in stmt.splitlines()):
                self._conn.execute(stmt)

    def columns(self, table: str) -> set[str]:
        if self.is_pg:
            return {r["column_name"] for r in self.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?", (table,))}
        return {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}

    def begin(self):
        self._conn.execute("BEGIN" if self.is_pg else "BEGIN IMMEDIATE")


def connect() -> Database:
    if DATABASE_URL:
        return Database(url=DATABASE_URL)
    return Database(path=DB_PATH)


def init_db(db: Database) -> None:
    db.executescript(_pg_schema(SCHEMA) if db.is_pg else SCHEMA)
    for table, column, kind in MIGRATIONS:
        if column not in db.columns(table):
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    db.executemany(
        "INSERT INTO materials (code, sort_order, label_en, label_hi, rate_per_kg, co2e_per_kg) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT (code) DO UPDATE SET sort_order = excluded.sort_order, "
        "label_en = excluded.label_en, label_hi = excluded.label_hi, rate_per_kg = excluded.rate_per_kg, "
        "co2e_per_kg = excluded.co2e_per_kg",
        MATERIALS,
    )


@contextmanager
def transaction(db: Database):
    db.begin()
    try:
        yield db
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def one(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None
