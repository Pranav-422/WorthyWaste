"""SQLite storage. Schema follows the Tech Spec data model; the pilot swaps this for PostgreSQL."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("WW_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("WW_DB", DATA_DIR / "worthywaste.db"))
PHOTO_DIR = DATA_DIR / "photos"

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
  lat         REAL NOT NULL,
  lng         REAL NOT NULL,
  scale_id    TEXT,
  upi_vpa     TEXT,
  reputation  INTEGER NOT NULL DEFAULT 80,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
  code         TEXT PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS recycler_sales (
  id            INTEGER PRIMARY KEY,
  dealer_id     INTEGER NOT NULL REFERENCES dealers(id),
  recycler_name TEXT NOT NULL,
  material      TEXT NOT NULL,
  kg            REAL NOT NULL,
  invoice_ref   TEXT NOT NULL,
  sold_at       TEXT NOT NULL
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

MATERIALS = [
    # code, English, Hindi, ₹/kg, kg CO2e avoided per kg (PET only, per Design Doc)
    ("plastic", "Plastic bottles", "प्लास्टिक बोतल", 12.4, 1.5),
    ("cardboard", "Cardboard", "गत्ता", 9.0, None),
    ("metal", "Cans & tin", "डिब्बे / टिन", 28.0, None),
    ("paper", "Newspaper", "अखबार", 11.0, None),
    ("wire", "Wire", "तार", 45.0, None),
    ("glass", "Glass", "कांच", 2.0, None),
]


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    conn.executescript(SCHEMA)
    # Additive migrations for databases created by an earlier version.
    if "meta_json" not in {r[1] for r in conn.execute("PRAGMA table_info(messages)")}:
        conn.execute("ALTER TABLE messages ADD COLUMN meta_json TEXT")
    conn.executemany(
        "INSERT OR IGNORE INTO materials (code, label_en, label_hi, rate_per_kg, co2e_per_kg) VALUES (?,?,?,?,?)",
        MATERIALS,
    )


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def one(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None
