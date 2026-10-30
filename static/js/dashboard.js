/* 台区负荷预测与异常用电预警系统 —— 前端交互逻辑 */

const state = {
  districtId: null,
  districts: [],
  charts: {},
  forecastData: null,
  forecastView: "evaluation",
  metrics: {},
};

const $ = (id) => document.getElementById(id);

function fmt(value, digits = 1) {
  const num = Number(value);
  if (value === null || value === undefined || Number.isNaN(num)) return "--";
  return num.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtInt(value) {
  const num = Number(value);
  if (value === null || value === undefined || Number.isNaN(num)) return "--";
  return num.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function pct(value, digits = 1) {
  const num = Number(value);
  if (value === null || value === undefined || Number.isNaN(num)) return "--";
  return `${fmt(num, digits)}%`;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setStatus(text, ok = true) {
  $("statusText").textContent = text;
  $("statusDot").style.background = ok ? "var(--teal-2)" : "var(--red)";
  $("statusDot").style.boxShadow = ok
    ? "0 0 0 4px rgba(43, 179, 163, 0.14)"
    : "0 0 0 4px rgba(211, 74, 74, 0.14)";
}

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`请求失败（HTTP ${response.status}）`);
  }
  return response.json();
}

function initCharts() {
  if (!window.echarts) {
    document.querySelectorAll(".chart").forEach((el) => {
      el.innerHTML =
        '<div class="chart-fallback">图表库加载失败。请联网后刷新页面，或把 ECharts 下载到本地 static/vendor 目录。</div>';
    });
    setStatus("图表库加载失败，但数据接口仍然可用", false);
    return false;
  }

  ["trendChart", "rankingChart", "forecastChart"].forEach((id) => {
    const el = $(id);
    if (el) state.charts[id] = window.echarts.init(el);
  });

  window.addEventListener("resize", () => {
    Object.values(state.charts).forEach((chart) => chart.resize());
  });
  return true;
}

function emptyChart(chart, text = "暂无数据") {
  if (!chart) return;
  chart.clear();
  chart.setOption({
    title: {
      text,
      left: "center",
      top: "middle",
      textStyle: { color: "#8a9bb3", fontSize: 13, fontWeight: "normal" },
    },
  });
}

async function loadDistricts() {
  const districts = await fetchJSON("/api/districts");
  state.districts = districts;

  const select = $("districtSelect");
  select.innerHTML = districts
    .map(
      (district) =>
        `<option value="${district.district_id}">${escapeHtml(district.name)}</option>`
    )
    .join("");

  state.districtId = Number(districts[0].district_id);
  select.value = String(state.districtId);

  select.addEventListener("change", () => {
    state.districtId = Number(select.value);
    const district = state.districts.find(
      (item) => Number(item.district_id) === state.districtId
    );
    $("districtType").textContent = district ? district.type : "--";
    loadDashboard();
  });
}

function updateHeader(overview) {
  const date = overview.latest_date || "--";
  $("latestDate").textContent = date;

  if (date && date !== "--") {
    const weekday = new Date(`${date}T00:00:00`).toLocaleDateString("zh-CN", {
      weekday: "long",
    });
    $("latestWeekday").textContent = `${weekday} · 数据已入库`;
  }

  const district = overview.district || {};
  $("districtType").textContent = district.type || "--";
}

function updateKpis(overview) {
  $("kpiMax").textContent = fmt(overview.max_load, 1);
  $("kpiAvg").textContent = fmt(overview.avg_load, 1);
  $("kpiEnergy").textContent = fmtInt(overview.energy_kwh);
  $("kpiAnomaly").textContent = fmtInt(overview.anomaly_count);
}

function updateModel(metrics) {
  const forecast = metrics.forecast || {};
  const anomaly = metrics.anomaly || {};
  const anomalyOverall = anomaly.overall || anomaly;

  $("metricMae").textContent = forecast.mae != null ? `${fmt(forecast.mae, 1)} kW` : "--";
  $("metricMape").textContent = forecast.mape != null ? pct(forecast.mape, 1) : "--";
  $("metricBaseline").textContent =
    forecast.baseline_mape != null ? pct(forecast.baseline_mape, 1) : "--";

  $("metricPrecision").textContent =
    anomalyOverall.precision != null ? pct(Number(anomalyOverall.precision) * 100, 1) : "--";
  $("metricRecall").textContent =
    anomalyOverall.recall != null ? pct(Number(anomalyOverall.recall) * 100, 1) : "--";
}

function renderTrend(data) {
  const chart = state.charts.trendChart;
  if (!chart) return;

  const labels = data.labels || [];
  if (!labels.length) {
    emptyChart(chart, "暂无负荷数据");
    return;
  }

  chart.setOption(
    {
      color: ["#178a83", "#d18a2d"],
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(10, 35, 66, 0.92)",
        borderWidth: 0,
        textStyle: { color: "#fff", fontSize: 12 },
        valueFormatter: (value) => `${fmt(value, 1)} kW`,
      },
      legend: {
        top: 4,
        right: 4,
        icon: "roundRect",
        itemWidth: 12,
        itemHeight: 4,
        textStyle: { color: "#71829a", fontSize: 11 },
      },
      grid: { left: 52, right: 20, top: 42, bottom: 28 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: labels,
        axisLine: { lineStyle: { color: "#dfe7f1" } },
        axisTick: { show: false },
        axisLabel: { color: "#71829a", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        name: "kW",
        nameTextStyle: { color: "#93a2b6", fontSize: 10 },
        splitLine: { lineStyle: { color: "#eef2f7" } },
        axisLabel: {
          color: "#71829a",
          fontSize: 11,
          formatter: (value) => (value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value),
        },
      },
      series: [
        {
          name: "日平均负荷",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: data.avg,
          lineStyle: { width: 3 },
          itemStyle: { borderWidth: 2, borderColor: "#fff" },
          areaStyle: {
            color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(23, 138, 131, 0.24)" },
              { offset: 1, color: "rgba(23, 138, 131, 0.01)" },
            ]),
          },
        },
        {
          name: "日最大负荷",
          type: "line",
          smooth: true,
          symbol: "none",
          data: data.max,
          lineStyle: { width: 2, type: "dashed" },
        },
      ],
      animationDuration: 650,
    },
    true
  );
}

function renderRanking(data) {
  const chart = state.charts.rankingChart;
  if (!chart) return;

  const items = (data.items || []).slice().reverse();
  if (!items.length) {
    emptyChart(chart, "暂无排名数据");
    return;
  }

  $("rankingDate").textContent = data.date ? `最新数据日 · ${data.date}` : "最新数据日";

  const names = items.map((item) => String(item.name).replace("台区", ""));
  const values = items.map((item) => Number(item.energy_kwh));
  const colors = items.map((item) =>
    Number(item.district_id) === state.districtId ? "#178a83" : "#c9d8e9"
  );

  chart.setOption(
    {
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "rgba(10, 35, 66, 0.92)",
        borderWidth: 0,
        textStyle: { color: "#fff", fontSize: 12 },
        valueFormatter: (value) => `${fmt(value, 1)} kWh`,
      },
      grid: { left: 92, right: 76, top: 12, bottom: 24 },
      xAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "#eef2f7" } },
        axisLabel: {
          color: "#71829a",
          fontSize: 10,
          formatter: (value) => (value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value),
        },
      },
      yAxis: {
        type: "category",
        data: names,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "#52647c", fontSize: 11 },
      },
      series: [
        {
          type: "bar",
          data: values.map((value, index) => ({
            value,
            itemStyle: { color: colors[index], borderRadius: [0, 5, 5, 0] },
          })),
          barWidth: 14,
          label: {
            show: true,
            position: "right",
            color: "#71829a",
            fontSize: 10,
            formatter: (params) => `${fmtInt(params.value)} kWh`,
          },
        },
      ],
      animationDuration: 650,
    },
    true
  );
}

function renderForecast(data, metrics) {
  const chart = state.charts.forecastChart;
  if (!chart) return;

  const isNext = state.forecastView === "next";
  const seriesData = isNext ? data.next_day : data.evaluation;

  if (!seriesData) {
    emptyChart(
      chart,
      isNext ? "暂无下一天预测，请先运行 ml/train.py" : "暂无测试日预测结果"
    );
    $("forecastMeta").textContent = "暂无预测结果";
    return;
  }

  if (isNext) {
    $("forecastMeta").textContent = `${seriesData.date} · 未来一天 96 点预测`;
  } else {
    const mape = metrics.forecast ? metrics.forecast.mape : null;
    $("forecastMeta").textContent = `${seriesData.date} · 96 点 · 测试集 MAPE ${
      mape != null ? pct(mape, 1) : "--"
    }`;
  }

  const series = isNext
    ? [
        {
          name: "下一天预测",
          type: "line",
          smooth: true,
          symbol: "none",
          data: seriesData.predicted,
          lineStyle: { width: 2.8, color: "#178a83" },
          areaStyle: {
            color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(23, 138, 131, 0.20)" },
              { offset: 1, color: "rgba(23, 138, 131, 0.01)" },
            ]),
          },
        },
      ]
    : [
        {
          name: "实际负荷",
          type: "line",
          smooth: true,
          symbol: "none",
          data: seriesData.actual,
          lineStyle: { width: 2.8, color: "#178a83" },
          areaStyle: {
            color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(23, 138, 131, 0.18)" },
              { offset: 1, color: "rgba(23, 138, 131, 0.01)" },
            ]),
          },
        },
        {
          name: "模型预测",
          type: "line",
          smooth: true,
          symbol: "none",
          data: seriesData.predicted,
          lineStyle: { width: 2.2, type: "dashed", color: "#d18a2d" },
        },
      ];

  chart.setOption(
    {
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(10, 35, 66, 0.92)",
        borderWidth: 0,
        textStyle: { color: "#fff", fontSize: 12 },
        valueFormatter: (value) => `${fmt(value, 1)} kW`,
      },
      legend: {
        top: 4,
        right: 4,
        icon: "roundRect",
        itemWidth: 12,
        itemHeight: 4,
        textStyle: { color: "#71829a", fontSize: 11 },
      },
      grid: { left: 52, right: 22, top: 44, bottom: 30 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: seriesData.times,
        axisLine: { lineStyle: { color: "#dfe7f1" } },
        axisTick: { show: false },
        axisLabel: {
          color: "#71829a",
          fontSize: 10,
          interval: 7,
        },
      },
      yAxis: {
        type: "value",
        name: "kW",
        nameTextStyle: { color: "#93a2b6", fontSize: 10 },
        splitLine: { lineStyle: { color: "#eef2f7" } },
        axisLabel: {
          color: "#71829a",
          fontSize: 11,
          formatter: (value) => (value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value),
        },
      },
      series,
      animationDuration: 700,
    },
    true
  );
}

function renderAnomalies(data) {
  const body = $("anomalyBody");
  const items = data.items || [];

  if (!items.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty">暂无异常记录</td></tr>';
    return;
  }

  body.innerHTML = items
    .map((item) => {
      const deviation = Number(item.deviation);
      const deviationClass = deviation >= 0 ? "text-danger" : "text-info";
      const levelClass = item.level === "严重" ? "badge-danger" : "badge-warn";
      return `
        <tr title="${escapeHtml(item.method || "")}">
          <td>${escapeHtml(item.date)}</td>
          <td>${escapeHtml(item.time)}</td>
          <td>${fmt(item.actual_kw, 1)} kW</td>
          <td>${fmt(item.expected_kw, 1)} kW</td>
          <td class="${deviationClass}">${deviation > 0 ? "+" : ""}${fmt(deviation, 1)}%</td>
          <td><span class="badge ${levelClass}">${escapeHtml(item.level)}</span></td>
        </tr>
      `;
    })
    .join("");
}

async function loadDashboard() {
  if (!state.districtId) return;
  setStatus("正在加载数据...");

  try {
    const id = state.districtId;
    const [overview, load, forecast, anomalies, ranking, metrics] = await Promise.all([
      fetchJSON(`/api/overview?district_id=${id}`),
      fetchJSON(`/api/load?district_id=${id}&days=7`),
      fetchJSON(`/api/forecast?district_id=${id}`),
      fetchJSON(`/api/anomalies?district_id=${id}&limit=30`),
      fetchJSON("/api/ranking"),
      fetchJSON(`/api/metrics?district_id=${id}`),
    ]);

    updateHeader(overview);
    updateKpis(overview);
    updateModel(metrics);
    renderTrend(load);
    renderRanking(ranking);
    state.forecastData = forecast;
    state.metrics = metrics;
    renderForecast(forecast, metrics);
    renderAnomalies(anomalies);

    const now = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setStatus(`已更新 · ${now}`);
  } catch (error) {
    console.error(error);
    setStatus(`加载失败：${error.message}`, false);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  initCharts();
  $("refreshBtn").addEventListener("click", loadDashboard);

  document.querySelectorAll("#forecastTabs .seg-btn").forEach((button) => {
    button.addEventListener("click", () => {
      document
        .querySelectorAll("#forecastTabs .seg-btn")
        .forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.forecastView = button.dataset.view;
      if (state.forecastData) {
        renderForecast(state.forecastData, state.metrics || {});
      }
    });
  });

  try {
    await loadDistricts();
    await loadDashboard();
  } catch (error) {
    console.error(error);
    setStatus(`初始化失败：${error.message}`, false);
  }
});
