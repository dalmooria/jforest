# jforest/db.py
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_pages (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL,
  page_type TEXT NOT NULL,
  ref_key TEXT NOT NULL,
  http_status INTEGER,
  body TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  UNIQUE (page_type, ref_key)
);
CREATE TABLE IF NOT EXISTS forests (
  instt_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  sido_code INTEGER,
  arcd TEXT,
  instt_type_code TEXT,
  instt_type TEXT,
  homepage_url TEXT,
  tags TEXT,
  summary TEXT,
  reservation_intake TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rooms (
  goods_id TEXT PRIMARY KEY,
  instt_id TEXT NOT NULL,
  room_type TEXT,
  name TEXT,
  capacity_standard INTEGER,
  capacity_max INTEGER,
  area TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_prices (
  id INTEGER PRIMARY KEY,
  goods_id TEXT NOT NULL,
  season TEXT NOT NULL,
  day_type TEXT NOT NULL,
  raw_label TEXT,
  price INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_usage_texts (
  goods_id TEXT PRIMARY KEY,
  checkin_time TEXT,
  checkout_time TEXT,
  amenities TEXT,
  usage_guide TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discount_policies (
  id INTEGER PRIMARY KEY,
  instt_id TEXT NOT NULL,
  target TEXT,
  category TEXT,
  timing TEXT,
  apply_date TEXT,
  room_rates TEXT,
  campsite_rate TEXT,
  facility_rate TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservation_policies (
  instt_id TEXT PRIMARY KEY,
  operates_rooms INTEGER,
  operates_campsite INTEGER,
  operates_waitlist INTEGER,
  fcfs_method TEXT,
  lottery_types TEXT,
  priority_types TEXT,
  fcfs_detail TEXT,
  lottery_detail TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservation_policy_details (
  instt_id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  menu_id TEXT,
  title TEXT,
  detail_text TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (instt_id, rule_id)
);
CREATE TABLE IF NOT EXISTS notices (
  instt_id TEXT NOT NULL,
  twbbs_id TEXT NOT NULL,
  title TEXT,
  updated_at TEXT,
  body_text TEXT,
  content_text TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (instt_id, twbbs_id)
);
CREATE TABLE IF NOT EXISTS notice_attachments (
  id INTEGER PRIMARY KEY,
  instt_id TEXT NOT NULL,
  twbbs_id TEXT NOT NULL,
  file_master_id TEXT,
  file_id TEXT,
  file_name TEXT,
  content_type TEXT,
  local_path TEXT,
  downloaded INTEGER DEFAULT 0,
  extracted_text TEXT,
  extraction_method TEXT,
  fetched_at TEXT NOT NULL,
  UNIQUE (file_master_id, file_id)
);
CREATE INDEX IF NOT EXISTS idx_natt_notice ON notice_attachments (instt_id, twbbs_id);
CREATE TABLE IF NOT EXISTS notice_facts (
  instt_id TEXT NOT NULL,
  twbbs_id TEXT NOT NULL,
  facts_json TEXT,
  model TEXT,
  needs_review INTEGER DEFAULT 0,
  extracted_at TEXT NOT NULL,
  PRIMARY KEY (instt_id, twbbs_id)
);
CREATE TABLE IF NOT EXISTS forest_facilities (
  instt_id TEXT PRIMARY KEY,
  water_play TEXT,
  barbecue TEXT,
  forest_guide TEXT,
  water_play_evidence TEXT,
  barbecue_evidence TEXT,
  forest_guide_evidence TEXT,
  model TEXT,
  needs_review INTEGER DEFAULT 0,
  extracted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fetch_log (
  id INTEGER PRIMARY KEY,
  url TEXT,
  http_status INTEGER,
  error TEXT,
  duration_ms INTEGER,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservation_blocks (
  id INTEGER PRIMARY KEY,
  instt_id TEXT NOT NULL,
  alert_type TEXT,
  scope TEXT,
  affected_units TEXT,
  start_date TEXT,
  end_date TEXT,
  reason TEXT,
  source_twbbs_id TEXT,
  needs_review INTEGER DEFAULT 0,
  extracted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blocks_instt ON reservation_blocks (instt_id);
"""


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """기존 DB에 누락된 컬럼을 추가한다(CREATE TABLE IF NOT EXISTS로는 안 되는 보정)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(notices)")]
    if cols and "content_text" not in cols:
        conn.execute("ALTER TABLE notices ADD COLUMN content_text TEXT")
    acols = [r[1] for r in conn.execute("PRAGMA table_info(notice_attachments)")]
    if acols and "extracted_text" not in acols:
        conn.execute("ALTER TABLE notice_attachments ADD COLUMN extracted_text TEXT")
    if acols and "extraction_method" not in acols:
        conn.execute("ALTER TABLE notice_attachments ADD COLUMN extraction_method TEXT")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def save_raw(conn, url, page_type, ref_key, http_status, body, fetched_at):
    conn.execute(
        "INSERT OR REPLACE INTO raw_pages "
        "(url, page_type, ref_key, http_status, body, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (url, page_type, ref_key, http_status, body, fetched_at),
    )
    conn.commit()


def get_raw_pages(conn, page_type) -> list:
    conn.row_factory = sqlite3.Row
    return list(conn.execute(
        "SELECT * FROM raw_pages WHERE page_type = ? ORDER BY ref_key",
        (page_type,),
    ))
