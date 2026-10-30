"""
训练短期负荷预测模型。

思路：
1. 从 SQLite 读取 96 点负荷数据。
2. 每个台区单独训练一个随机森林模型（不同台区负荷规律差异很大）。
3. 用“前 50 天训练、后 10 天测试”的方式做时间序列切分，避免数据泄漏。
4. 输出 MAE、MAPE，并与“昨天同一时刻”的基线模型对比。
5. 保存模型、评估指标，以及“最后一天”和“下一天”的预测结果。

运行方式（在项目根目录，先运行 init_db.py）：
    python ml/train.py
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "grid.db"
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# 模型输入特征
FEATURES = [
    "time_index",
    "hour",
    "weekday",
    "is_weekend",
    "temperature",
    "is_holiday",
    "lag_1d",
    "lag_7d",
    "prev_load",
    "rolling_mean_4",
    "rolling_mean_96",
]
TARGET = "load_kw"


def load_data() -> pd.DataFrame:
    """从数据库读取负荷明细。"""
    if not DB_PATH.exists():
        raise SystemExit("数据库不存在，请先运行：python scripts/init_db.py")

    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            """
            SELECT district_id, date, time_index, load_kw, temperature,
                   is_holiday, is_injected_anomaly
            FROM load_data
            ORDER BY district_id, date, time_index
            """,
            conn,
        )
    finally:
        conn.close()

    df["date"] = pd.to_datetime(df["date"])
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """构造时间特征、滞后特征和滑动统计特征。"""
    df = df.sort_values(["district_id", "date", "time_index"]).copy()

    # 缺失负荷用线性插值补齐；如果整段都缺失，再用该台区中位数兜底
    df["load_kw"] = df.groupby("district_id")["load_kw"].transform(
        lambda s: s.interpolate(limit_direction="both")
    )
    df["load_kw"] = df.groupby("district_id")["load_kw"].transform(
        lambda s: s.fillna(s.median())
    )

    df["hour"] = df["time_index"] / 4.0
    df["weekday"] = df["date"].dt.weekday
    df["is_weekend"] = (df["weekday"] >= 5).astype(int)

    # 滞后特征：昨天同一时刻、上周同一时刻
    df["lag_1d"] = df.groupby("district_id")["load_kw"].shift(96)
    df["lag_7d"] = df.groupby("district_id")["load_kw"].shift(96 * 7)
    df["lag_7d"] = df["lag_7d"].fillna(df["lag_1d"])

    # 上一个 15 分钟负荷，以及最近 1 小时/最近 1 天的滑动平均
    df["prev_load"] = df.groupby("district_id")["load_kw"].shift(1)
    df["rolling_mean_4"] = df.groupby("district_id")["prev_load"].transform(
        lambda s: s.rolling(4, min_periods=1).mean()
    )
    df["rolling_mean_96"] = df.groupby("district_id")["prev_load"].transform(
        lambda s: s.rolling(96, min_periods=1).mean()
    )

    # 每个台区第一天没有“昨天”的数据，直接丢掉
    df = df.dropna(subset=FEATURES + [TARGET]).reset_index(drop=True)
    return df


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """平均绝对百分比误差，单位是 %。"""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = np.abs(y_true) > 1e-6
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def build_next_day_features(
    df: pd.DataFrame,
    district_id: int,
    last_date: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """
    递推构造“下一天”96 个点的特征。

    说明：
    - 00:00 的“上一个 15 分钟”是最后一天 23:45，这是已知的。
    - 00:15 之后的“上一个 15 分钟”只能用模型刚刚预测出来的值，所以叫递推预测。
    - lag_1d 和 lag_7d 都是历史真实值，不参与递推。
    """
    district_df = df[df["district_id"] == district_id].sort_values(["date", "time_index"])

    last_day = district_df[district_df["date"] == last_date].sort_values("time_index")
    if len(last_day) != 96:
        raise ValueError(f"台区 {district_id} 最后一天不是 96 个点，实际 {len(last_day)} 个")

    lag7_date = last_date - pd.Timedelta(days=6)  # 下一天往前推 7 天
    lag7_day = district_df[district_df["date"] == lag7_date].sort_values("time_index")
    if len(lag7_day) != 96:
        raise ValueError(f"台区 {district_id} 缺少 {lag7_date.date()} 的 96 点数据")

    last_values = last_day["load_kw"].to_numpy(dtype=float)
    lag7_values = lag7_day["load_kw"].to_numpy(dtype=float)
    last_temps = last_day["temperature"].to_numpy(dtype=float)

    next_date = last_date + pd.Timedelta(days=1)
    next_weekday = next_date.weekday()
    history = list(last_values)

    rows: list[dict] = []
    for t in range(96):
        row = {
            "time_index": t,
            "hour": t / 4.0,
            "weekday": next_weekday,
            "is_weekend": int(next_weekday >= 5),
            "temperature": float(last_temps[t]),
            "is_holiday": 0,
            "lag_1d": float(last_values[t]),
            "lag_7d": float(lag7_values[t]),
            "prev_load": float(history[-1]),
            "rolling_mean_4": float(np.mean(history[-4:])),
            "rolling_mean_96": float(np.mean(history[-96:])),
        }
        rows.append(row)

    return pd.DataFrame(rows)[FEATURES], next_date


def main() -> None:
    print("Loading data ...")
    raw_df = load_data()
    df = add_features(raw_df)
    last_date = df["date"].max()
    test_start = last_date - pd.Timedelta(days=9)  # 最后 10 天做测试

    print(f"Data rows after feature engineering: {len(df):,}")
    print(f"Train: date < {test_start.date()} | Test: {test_start.date()} ~ {last_date.date()}")

    models: dict[int, RandomForestRegressor] = {}
    district_metrics: dict[str, dict] = {}
    forecast_rows: list[tuple] = []

    for district_id in sorted(df["district_id"].unique()):
        district_df = df[df["district_id"] == district_id].copy()
        train_df = district_df[district_df["date"] < test_start]
        test_df = district_df[district_df["date"] >= test_start]

        if len(train_df) < 100 or len(test_df) < 96:
            print(f"Skip district {district_id}: not enough data")
            continue

        model = RandomForestRegressor(
            n_estimators=200,
            max_depth=14,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=1,
        )
        model.fit(train_df[FEATURES], train_df[TARGET])

        pred = model.predict(test_df[FEATURES])
        actual = test_df[TARGET].to_numpy(dtype=float)
        baseline = test_df["lag_1d"].to_numpy(dtype=float)

        metrics = {
            "district_id": int(district_id),
            "mae": round(mae(actual, pred), 3),
            "mape": round(mape(actual, pred), 3),
            "baseline_mae": round(mae(actual, baseline), 3),
            "baseline_mape": round(mape(actual, baseline), 3),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
        }
        district_metrics[str(district_id)] = metrics
        models[int(district_id)] = model
        print(
            f"District {district_id}: MAE={metrics['mae']:.2f}, "
            f"MAPE={metrics['mape']:.2f}%, "
            f"baseline MAPE={metrics['baseline_mape']:.2f}%"
        )

        # 保存测试集最后一天的“实际 vs 预测”，用于看板对比
        eval_date = test_df["date"].max()
        eval_last = test_df[test_df["date"] == eval_date].sort_values("time_index")
        eval_pred = model.predict(eval_last[FEATURES])
        for t, p, a in zip(
            eval_last["time_index"].astype(int),
            eval_pred,
            eval_last[TARGET].astype(float),
        ):
            forecast_rows.append(
                (
                    int(district_id),
                    eval_date.strftime("%Y-%m-%d"),
                    int(t),
                    float(p),
                    float(a),
                    1,
                )
            )

        # 递推预测下一天
        next_features, next_date = build_next_day_features(df, int(district_id), last_date)
        next_pred = model.predict(next_features)
        next_pred = np.maximum(next_pred, 0.0)
        for t, p in enumerate(next_pred):
            forecast_rows.append(
                (
                    int(district_id),
                    next_date.strftime("%Y-%m-%d"),
                    int(t),
                    float(p),
                    None,
                    0,
                )
            )

    if not models:
        raise SystemExit("没有训练出任何模型，请检查数据。")

    # 总体指标：各台区简单平均
    overall = {
        "mae": round(float(np.mean([m["mae"] for m in district_metrics.values()])), 3),
        "mape": round(float(np.mean([m["mape"] for m in district_metrics.values()])), 3),
        "baseline_mae": round(
            float(np.mean([m["baseline_mae"] for m in district_metrics.values()])), 3
        ),
        "baseline_mape": round(
            float(np.mean([m["baseline_mape"] for m in district_metrics.values()])), 3
        ),
    }

    # 保存模型和指标
    joblib.dump(models, MODEL_DIR / "forecast_models.joblib")
    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test_days": 10,
        "features": FEATURES,
        "districts": district_metrics,
        "overall": overall,
    }
    (MODEL_DIR / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 写入数据库：预测结果 + 指标
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM forecasts")
        conn.executemany(
            """
            INSERT OR REPLACE INTO forecasts
                (district_id, target_date, time_index, predicted_kw, actual_kw, is_evaluation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            forecast_rows,
        )

        conn.execute("DELETE FROM model_metrics")
        for district_id, m in district_metrics.items():
            conn.execute(
                """
                INSERT INTO model_metrics
                    (district_id, mae, mape, baseline_mae, baseline_mape,
                     train_rows, test_rows, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(district_id),
                    m["mae"],
                    m["mape"],
                    m["baseline_mae"],
                    m["baseline_mape"],
                    m["train_rows"],
                    m["test_rows"],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    print("=" * 60)
    print("Training finished")
    print(f"Overall MAE: {overall['mae']:.2f} kW")
    print(f"Overall MAPE: {overall['mape']:.2f}%")
    print(f"Baseline MAPE: {overall['baseline_mape']:.2f}%")
    print(f"Models: {MODEL_DIR / 'forecast_models.joblib'}")
    print(f"Metrics: {MODEL_DIR / 'metrics.json'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
