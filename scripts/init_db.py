"""
把 CSV 数据导入 SQLite 数据库。

运行方式（在项目根目录）：
    python scripts/init_db.py

为什么用 SQLite？
- 不需要安装 MySQL，零配置，适合单机演示。
- Python 标准库自带 sqlite3，面试时也容易解释。
- 生产环境可以换成 MySQL/PostgreSQL，项目结构不用大改。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "grid.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS districts (
    district_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,
    base_load REAL
);

CREATE TABLE IF NOT EXISTS load_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    district_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    time_index INTEGER NOT NULL,
    load_kw REAL,
    temperature REAL,
    is_holiday INTEGER DEFAULT 0,
    is_injected_anomaly INTEGER DEFAULT 0,
    UNIQUE (district_id, date, time_index)
);

CREATE INDEX IF NOT EXISTS idx_load_district_date
    ON load_data (district_id, date, time_index);

CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    district_id INTEGER NOT NULL,
    target_date TEXT NOT NULL,
    time_index INTEGER NOT NULL,
    predicted_kw REAL,
    actual_kw REAL,
    is_evaluation INTEGER DEFAULT 0,
    UNIQUE (district_id, target_date, time_index, is_evaluation)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    district_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    time_index INTEGER NOT NULL,
    actual_kw REAL,
    expected_kw REAL,
    deviation REAL,
    level TEXT,
    method TEXT,
    UNIQUE (district_id, date, time_index)
);

CREATE TABLE IF NOT EXISTS model_metrics (
    district_id INTEGER PRIMARY KEY,
    mae REAL,
    mape REAL,
    baseline_mae REAL,
    baseline_mape REAL,
    train_rows INTEGER,
    test_rows INTEGER,
    updated_at TEXT
);
"""


def main() -> None:
    load_csv = DATA_DIR / "load_data.csv"
    districts_csv = DATA_DIR / "districts.csv"

    if not load_csv.exists() or not districts_csv.exists():
        raise SystemExit("Data files not found. Run: python data/generate_data.py")

    print("Reading CSV ...")
    load_df = pd.read_csv(load_csv, encoding="utf-8-sig")
    districts_df = pd.read_csv(districts_csv, encoding="utf-8-sig")

    # 删除完全重复的行；同一台区同一天同一时刻只保留一条
    before = len(load_df)
    load_df = load_df.drop_duplicates(
        subset=["district_id", "date", "time_index"], keep="first"
    )
    print(f"Deduplicate: {before:,} -> {len(load_df):,} rows")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)

        # 每次重建基础数据时，清空旧的分析结果，避免脏数据
        conn.execute("DELETE FROM forecasts")
        conn.execute("DELETE FROM anomalies")
        conn.execute("DELETE FROM model_metrics")
        conn.execute("DELETE FROM load_data")
        conn.execute("DELETE FROM districts")

        conn.executemany(
            """
            INSERT INTO districts (district_id, name, type, base_load)
            VALUES (?, ?, ?, ?)
            """,
            districts_df[
                ["district_id", "name", "type", "base_load"]
            ].itertuples(index=False, name=None),
        )

        rows = load_df[
            [
                "district_id",
                "date",
                "time_index",
                "load_kw",
                "temperature",
                "is_holiday",
                "is_injected_anomaly",
            ]
        ].itertuples(index=False, name=None)

        conn.executemany(
            """
            INSERT OR IGNORE INTO load_data
                (district_id, date, time_index, load_kw, temperature,
                 is_holiday, is_injected_anomaly)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

        district_count = conn.execute("SELECT COUNT(*) FROM districts").fetchone()[0]
        load_count = conn.execute("SELECT COUNT(*) FROM load_data").fetchone()[0]

    finally:
        conn.close()

    print("=" * 60)
    print("Database initialized")
    print(f"DB file: {DB_PATH}")
    print(f"Districts: {district_count}")
    print(f"Load rows: {load_count:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
