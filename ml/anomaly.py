"""
异常用电检测。

方法：
1. 对每个台区、每个时刻（96 个时刻分别看），取过去 7 天同一时刻负荷的中位数，
   作为“这个时刻应该有的负荷”。
2. 计算实际值与期望值的残差，再用稳健 Z 分数（基于 MAD）判断是否异常。
3. 同时要求偏差超过 20%，减少把正常波动误判为异常。

为什么用中位数和 MAD？
- 中位数不受极端值影响，比平均值更稳健。
- MAD（绝对中位差）比标准差更不容易被异常点“带偏”。

运行方式（在项目根目录，先运行 init_db.py）：
    python ml/anomaly.py
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "grid.db"
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

Z_THRESHOLD = 4.5
MIN_DEVIATION = 0.20  # 20%


def load_data() -> pd.DataFrame:
    if not DB_PATH.exists():
        raise SystemExit("数据库不存在，请先运行：python scripts/init_db.py")

    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            """
            SELECT district_id, date, time_index, load_kw, is_injected_anomaly
            FROM load_data
            ORDER BY district_id, date, time_index
            """,
            conn,
        )
    finally:
        conn.close()

    df["date"] = pd.to_datetime(df["date"])
    return df


def detect(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """返回异常明细和评估指标。"""
    df = df.sort_values(["district_id", "date", "time_index"]).copy()

    # 同一台区、同一时刻，取过去 7 天的中位数（shift(1) 表示不包含当天）
    df["expected_kw"] = df.groupby(["district_id", "time_index"])["load_kw"].transform(
        lambda s: s.rolling(7, min_periods=3).median().shift(1)
    )
    df["residual"] = df["load_kw"] - df["expected_kw"]
    df["deviation"] = df["residual"] / df["expected_kw"]

    results: list[pd.DataFrame] = []
    district_metrics: dict[str, dict] = {}

    for district_id, part in df.groupby("district_id"):
        part = part.copy()
        valid = part["residual"].notna()
        residual = part.loc[valid, "residual"]

        median = float(residual.median())
        mad = float((residual - median).abs().median())
        sigma = 1.4826 * mad
        if sigma < 1e-6:
            sigma = float(residual.std())
        if sigma < 1e-6:
            sigma = 1.0

        part["robust_z"] = (part["residual"] - median) / sigma

        flagged = (
            valid
            & (part["robust_z"].abs() >= Z_THRESHOLD)
            & (part["deviation"].abs() >= MIN_DEVIATION)
        )
        part["is_anomaly"] = flagged.astype(int)

        # 与注入的“真实异常”对比，计算召回率和精确率
        labeled = valid & (part["is_injected_anomaly"] == 1)
        tp = int((flagged & labeled).sum())
        fp = int((flagged & valid & ~labeled).sum())
        fn = int((~flagged & labeled).sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        district_metrics[str(int(district_id))] = {
            "flagged": int(flagged.sum()),
            "injected": int(labeled.sum()),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "sigma": round(sigma, 4),
            "z_threshold": Z_THRESHOLD,
            "min_deviation": MIN_DEVIATION,
        }
        results.append(part)

    all_df = pd.concat(results, ignore_index=True)
    anomalies = all_df[all_df["is_anomaly"] == 1].copy()

    total_tp = sum(m["tp"] for m in district_metrics.values())
    total_fp = sum(m["fp"] for m in district_metrics.values())
    total_fn = sum(m["fn"] for m in district_metrics.values())
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    overall = {
        "flagged": int(len(anomalies)),
        # 只统计“期望值可计算”的注入异常，保证 precision/recall 口径一致
        "injected": total_tp + total_fn,
        "injected_total": int(all_df["is_injected_anomaly"].sum()),
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }
    return anomalies, {"overall": overall, "districts": district_metrics}


def level_of(row: pd.Series) -> str:
    """异常等级：偏差越大、Z 分数越高，等级越高。"""
    if abs(row["deviation"]) >= 0.50 or abs(row["robust_z"]) >= 6:
        return "严重"
    return "警告"


def main() -> None:
    print("Loading data ...")
    df = load_data()
    anomalies, metrics = detect(df)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM anomalies")
        rows = []
        for _, row in anomalies.iterrows():
            rows.append(
                (
                    int(row["district_id"]),
                    row["date"].strftime("%Y-%m-%d"),
                    int(row["time_index"]),
                    float(row["load_kw"]),
                    float(row["expected_kw"]),
                    round(float(row["deviation"]) * 100, 2),
                    level_of(row),
                    "同时段7天中位数 + 稳健3σ",
                )
            )
        conn.executemany(
            """
            INSERT OR REPLACE INTO anomalies
                (district_id, date, time_index, actual_kw, expected_kw,
                 deviation, level, method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "method": "同时段7天中位数 + 稳健3σ",
        **metrics,
    }
    (MODEL_DIR / "anomaly_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    overall = metrics["overall"]
    print("=" * 60)
    print("Anomaly detection finished")
    print(f"Flagged: {overall['flagged']} | Injected: {overall['injected']}")
    print(
        f"Precision={overall['precision']:.2%}, "
        f"Recall={overall['recall']:.2%}, F1={overall['f1']:.2%}"
    )
    print(f"Metrics: {MODEL_DIR / 'anomaly_metrics.json'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
