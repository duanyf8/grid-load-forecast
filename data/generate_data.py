"""
生成模拟的台区 96 点负荷数据。

说明：
1. 真实台区负荷数据涉及用户隐私，学生项目一般拿不到。
2. 这里用“日周期 + 周周期 + 温度影响 + 随机噪声”生成一份结构接近真实业务的数据。
3. 数据里故意加入少量缺失值、重复值和异常点，方便后面练习数据清洗与异常检测。

运行方式（在项目根目录）：
    python data/generate_data.py

生成文件：
    data/districts.csv   台区档案
    data/load_data.csv   96 点负荷明细
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# 固定随机种子，保证每次生成的数据一样，方便复现实验结果
np.random.seed(42)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 五个台区：居民、工业、商业混合，负荷曲线会略有差异
DISTRICTS = [
    {"district_id": 1, "name": "滨河小区台区", "type": "居民", "base_load": 320.0},
    {"district_id": 2, "name": "高新产业园台区", "type": "工业", "base_load": 680.0},
    {"district_id": 3, "name": "中心商业街台区", "type": "商业", "base_load": 450.0},
    {"district_id": 4, "name": "大学城台区", "type": "居民", "base_load": 380.0},
    {"district_id": 5, "name": "城郊安置区台区", "type": "居民", "base_load": 260.0},
]

START_DATE = date(2026, 9, 1)
DAYS = 60
POINTS_PER_DAY = 96  # 每 15 分钟一个点，一天 96 点


def daily_shape(hour: float) -> float:
    """返回一天 24 小时的负荷形状，早晚双高峰。"""
    morning = 0.65 * np.exp(-((hour - 9.5) ** 2) / 7.0)
    evening = 1.00 * np.exp(-((hour - 19.5) ** 2) / 5.5)
    noon = 0.30 * np.exp(-((hour - 13.0) ** 2) / 9.0)
    return 0.55 + morning + evening + noon


def weekday_factor(district_type: str, weekday: int) -> float:
    """周末对不同类型的台区影响不同。"""
    is_weekend = weekday >= 5
    if district_type == "工业":
        return 0.82 if is_weekend else 1.00
    if district_type == "商业":
        return 1.10 if is_weekend else 1.00
    # 居民台区周末白天略高
    return 1.06 if is_weekend else 1.00


def temperature_for(day_index: int, hour: float) -> float:
    """模拟 9-10 月气温：整体缓慢下降，日内午后高、凌晨低。"""
    seasonal = 26.0 - 0.16 * day_index
    daily = 4.0 * np.sin((hour - 9.0) / 24.0 * 2 * np.pi)
    noise = np.random.normal(0, 0.8)
    return round(seasonal + daily + noise, 2)


def build_rows() -> pd.DataFrame:
    rows: list[dict] = []

    for d in DISTRICTS:
        for day_index in range(DAYS):
            current_date = START_DATE + timedelta(days=day_index)
            weekday = current_date.weekday()
            wf = weekday_factor(d["type"], weekday)

            for t in range(POINTS_PER_DAY):
                hour = t / 4.0
                temp = temperature_for(day_index, hour)

                # 基础负荷 × 日曲线 × 周末系数 × 温度系数
                temp_factor = 1.0 + (0.008 if d["type"] != "工业" else 0.003) * (temp - 22.0)
                trend = 1.0 + 0.020 * (day_index / DAYS)  # 轻微增长趋势
                base = d["base_load"] * daily_shape(hour) * wf * temp_factor * trend
                noise = np.random.normal(0, 0.025 * d["base_load"])
                load = max(30.0, base + noise)

                rows.append(
                    {
                        "district_id": d["district_id"],
                        "date": current_date.isoformat(),
                        "time_index": t,
                        "load_kw": round(float(load), 2),
                        "temperature": temp,
                        "is_holiday": 0,
                        "is_injected_anomaly": 0,
                    }
                )

    df = pd.DataFrame(rows)

    # ---------- 故意注入异常：方便验证异常检测效果 ----------
    # 每个台区挑 4 天，在一天中挑一段连续时间，整体抬高或压低负荷
    for district_id in df["district_id"].unique():
        district_mask = df["district_id"] == district_id
        dates = sorted(df.loc[district_mask, "date"].unique())
        chosen_days = np.random.choice(dates, size=4, replace=False)

        for chosen_date in chosen_days:
            start_t = np.random.randint(20, 70)
            duration = np.random.randint(8, 25)
            end_t = min(start_t + duration, POINTS_PER_DAY)
            mask = (
                district_mask
                & (df["date"] == chosen_date)
                & (df["time_index"] >= start_t)
                & (df["time_index"] < end_t)
            )
            factor = np.random.choice([0.35, 0.5, 1.8, 2.2])
            df.loc[mask, "load_kw"] = (df.loc[mask, "load_kw"] * factor).round(2)
            df.loc[mask, "is_injected_anomaly"] = 1

    # 再随机注入少量“尖峰/骤降”单点异常
    n_points = len(df)
    point_indices = np.random.choice(n_points, size=int(n_points * 0.0015), replace=False)
    for idx in point_indices:
        factor = np.random.choice([0.25, 0.4, 2.0, 2.8])
        df.loc[idx, "load_kw"] = round(float(df.loc[idx, "load_kw"] * factor), 2)
        df.loc[idx, "is_injected_anomaly"] = 1

    # ---------- 故意制造缺失值和重复值，练习数据清洗 ----------
    missing_indices = np.random.choice(n_points, size=int(n_points * 0.001), replace=False)
    df.loc[missing_indices, "load_kw"] = np.nan

    duplicate_rows = df.sample(n=30, random_state=7)
    df = pd.concat([df, duplicate_rows], ignore_index=True)

    return df


def main() -> None:
    districts_df = pd.DataFrame(DISTRICTS)
    districts_df.to_csv(DATA_DIR / "districts.csv", index=False, encoding="utf-8-sig")

    df = build_rows()
    df.to_csv(DATA_DIR / "load_data.csv", index=False, encoding="utf-8-sig")

    print("=" * 60)
    print("模拟数据生成完成")
    print(f"台区数量：{df['district_id'].nunique()}")
    print(f"日期范围：{df['date'].min()} 至 {df['date'].max()}")
    print(f"负荷记录：{len(df):,} 行（含 30 行重复数据）")
    print(f"缺失负荷：{df['load_kw'].isna().sum()} 行")
    print(f"注入异常：{int(df['is_injected_anomaly'].sum())} 行")
    print(f"输出文件：{DATA_DIR / 'load_data.csv'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
