"""
Flask 后端：提供看板页面和 JSON API。

运行方式（在项目根目录）：
    python app.py

然后浏览器打开：
    http://127.0.0.1:5000
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "grid.db"
MODEL_DIR = BASE_DIR / "models"

app = Flask(__name__)
app.json.ensure_ascii = False


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """执行查询并返回 DataFrame。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()) -> dict:
    df = query_df(sql, params)
    if df.empty:
        return {}
    return records(df)[0]


def records(df: pd.DataFrame) -> list[dict]:
    """把 DataFrame 转成能安全 JSON 序列化的列表。"""
    return json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))


def get_district_id() -> int:
    try:
        return int(request.args.get("district_id", 1))
    except (TypeError, ValueError):
        return 1


def time_label(time_index: int) -> str:
    hour = time_index // 4
    minute = (time_index % 4) * 15
    return f"{hour:02d}:{minute:02d}"


@app.get("/")
def index():
    if not DB_PATH.exists():
        return (
            "<h2>数据库还没有初始化</h2>"
            "<p>请先在项目根目录依次运行：</p>"
            "<pre>python data/generate_data.py\n"
            "python scripts/init_db.py\n"
            "python ml/train.py\n"
            "python ml/anomaly.py</pre>",
            500,
        )
    return render_template("index.html")


@app.get("/api/districts")
def api_districts():
    df = query_df(
        "SELECT district_id, name, type, base_load FROM districts ORDER BY district_id"
    )
    return jsonify(records(df))


@app.get("/api/overview")
def api_overview():
    district_id = get_district_id()
    district = query_one(
        "SELECT district_id, name, type, base_load FROM districts WHERE district_id = ?",
        (district_id,),
    )
    latest = query_one(
        "SELECT MAX(date) AS latest_date FROM load_data WHERE district_id = ?",
        (district_id,),
    )
    latest_date = latest.get("latest_date")
    if not latest_date:
        return jsonify({"error": "没有找到该台区的数据"}), 404

    day = query_one(
        """
        SELECT MAX(load_kw) AS max_load,
               AVG(load_kw) AS avg_load,
               SUM(load_kw) * 0.25 AS energy_kwh
        FROM load_data
        WHERE district_id = ? AND date = ?
        """,
        (district_id, latest_date),
    )

    anomaly = query_one(
        """
        SELECT COUNT(*) AS anomaly_count
        FROM anomalies
        WHERE district_id = ? AND date >= date(?, '-6 days')
        """,
        (district_id, latest_date),
    )

    metrics = query_one(
        """
        SELECT mae, mape, baseline_mae, baseline_mape, train_rows, test_rows
        FROM model_metrics WHERE district_id = ?
        """,
        (district_id,),
    )

    return jsonify(
        {
            "district": district,
            "latest_date": latest_date,
            "max_load": round(float(day.get("max_load") or 0), 2),
            "avg_load": round(float(day.get("avg_load") or 0), 2),
            "energy_kwh": round(float(day.get("energy_kwh") or 0), 2),
            "anomaly_count": int(anomaly.get("anomaly_count") or 0),
            "metrics": metrics,
        }
    )


@app.get("/api/load")
def api_load():
    district_id = get_district_id()
    days = request.args.get("days", 7, type=int)
    days = max(3, min(days, 30))

    df = query_df(
        """
        SELECT date, AVG(load_kw) AS avg_load, MAX(load_kw) AS max_load
        FROM load_data
        WHERE district_id = ?
        GROUP BY date
        ORDER BY date DESC
        LIMIT ?
        """,
        (district_id, days),
    )
    df = df.sort_values("date").reset_index(drop=True)
    df["label"] = pd.to_datetime(df["date"]).dt.strftime("%m-%d")
    return jsonify(
        {
            "labels": df["label"].tolist(),
            "avg": [round(float(x), 2) for x in df["avg_load"]],
            "max": [round(float(x), 2) for x in df["max_load"]],
        }
    )


@app.get("/api/forecast")
def api_forecast():
    district_id = get_district_id()

    eval_meta = query_one(
        """
        SELECT MAX(target_date) AS d
        FROM forecasts
        WHERE district_id = ? AND is_evaluation = 1
        """,
        (district_id,),
    )
    next_meta = query_one(
        """
        SELECT MAX(target_date) AS d
        FROM forecasts
        WHERE district_id = ? AND is_evaluation = 0
        """,
        (district_id,),
    )

    response = {"evaluation": None, "next_day": None}

    if eval_meta.get("d"):
        eval_df = query_df(
            """
            SELECT time_index, predicted_kw, actual_kw
            FROM forecasts
            WHERE district_id = ? AND target_date = ? AND is_evaluation = 1
            ORDER BY time_index
            """,
            (district_id, eval_meta["d"]),
        )
        if not eval_df.empty:
            response["evaluation"] = {
                "date": eval_meta["d"],
                "times": [time_label(int(t)) for t in eval_df["time_index"]],
                "actual": [round(float(x), 2) for x in eval_df["actual_kw"]],
                "predicted": [round(float(x), 2) for x in eval_df["predicted_kw"]],
            }

    if next_meta.get("d"):
        next_df = query_df(
            """
            SELECT time_index, predicted_kw
            FROM forecasts
            WHERE district_id = ? AND target_date = ? AND is_evaluation = 0
            ORDER BY time_index
            """,
            (district_id, next_meta["d"]),
        )
        if not next_df.empty:
            response["next_day"] = {
                "date": next_meta["d"],
                "times": [time_label(int(t)) for t in next_df["time_index"]],
                "predicted": [round(float(x), 2) for x in next_df["predicted_kw"]],
            }

    return jsonify(response)


@app.get("/api/anomalies")
def api_anomalies():
    district_id = get_district_id()
    limit = request.args.get("limit", 30, type=int)
    limit = max(5, min(limit, 200))

    df = query_df(
        """
        SELECT date, time_index, actual_kw, expected_kw, deviation, level, method
        FROM anomalies
        WHERE district_id = ?
        ORDER BY date DESC, time_index DESC
        LIMIT ?
        """,
        (district_id, limit),
    )
    items = records(df)
    for item in items:
        item["time"] = time_label(int(item["time_index"]))
        item["actual_kw"] = round(float(item["actual_kw"]), 2)
        item["expected_kw"] = round(float(item["expected_kw"]), 2)
        item["deviation"] = round(float(item["deviation"]), 2)
        item.pop("time_index", None)
    return jsonify({"items": items})


@app.get("/api/ranking")
def api_ranking():
    latest = query_one("SELECT MAX(date) AS d FROM load_data")
    latest_date = latest.get("d")
    if not latest_date:
        return jsonify({"date": None, "items": []})

    df = query_df(
        """
        SELECT d.district_id, d.name, SUM(l.load_kw) * 0.25 AS energy_kwh
        FROM districts d
        JOIN load_data l ON l.district_id = d.district_id
        WHERE l.date = ?
        GROUP BY d.district_id, d.name
        ORDER BY energy_kwh DESC
        """,
        (latest_date,),
    )
    items = records(df)
    for item in items:
        item["energy_kwh"] = round(float(item["energy_kwh"]), 2)
    return jsonify({"date": latest_date, "items": items})


@app.get("/api/metrics")
def api_metrics():
    district_id = get_district_id()
    forecast = query_one(
        """
        SELECT mae, mape, baseline_mae, baseline_mape, train_rows, test_rows
        FROM model_metrics WHERE district_id = ?
        """,
        (district_id,),
    )

    anomaly_path = MODEL_DIR / "anomaly_metrics.json"
    anomaly = {}
    if anomaly_path.exists():
        all_metrics = json.loads(anomaly_path.read_text(encoding="utf-8"))
        anomaly = all_metrics.get("districts", {}).get(str(district_id), {})
        anomaly["overall"] = all_metrics.get("overall", {})
        anomaly["method"] = all_metrics.get("method", "")

    return jsonify({"forecast": forecast, "anomaly": anomaly})


if __name__ == "__main__":
    print("=" * 60)
    print("台区负荷预测与异常用电预警系统")
    print("请在浏览器打开：http://127.0.0.1:5000")
    print("按 Ctrl+C 停止服务")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
