# 台区短期负荷预测与异常用电预警系统

> **Python + Flask + SQLite + scikit-learn + ECharts**。  
> 不依赖硬件、不依赖真实用户数据，一台普通电脑即可跑通。

<!-- 运行后截图放到 docs/screenshots/dashboard.png，并取消下面这行注释 -->
<!-- ![看板截图](docs/screenshots/dashboard.png) -->

## 1. 项目简介

配电台区需要提前掌握负荷变化，也需要发现异常用电行为。  
本项目用模拟的 **96 点负荷数据**（每 15 分钟一个点，一天 96 点）完成三件事：

1. **短期负荷预测**：预测未来一天 96 个时刻的负荷曲线。
2. **异常用电筛查**：找出明显偏离历史规律的负荷点，输出异常清单。
3. **可视化看板**：用图表展示负荷趋势、预测对比、台区排名和异常明细。

项目重点不是“模型多复杂”，而是完整走通：

> 数据生成 → 数据清洗 → 特征工程 → 模型训练 → 评估 → API → 可视化 → 文档

这条链路在电网信息化、数据分析、软件开发类岗位的面试中都能讲。

## 2. 功能清单

- 5 个台区、60 天、每天 96 点的模拟负荷数据
- 缺失值、重复值、异常点的清洗
- 时间特征、滞后特征、滑动统计特征
- 每个台区独立训练随机森林预测模型
- 时间序列切分：前 50 天训练，后 10 天测试
- MAE、MAPE 评估，并与“昨天同时刻”基线对比
- 未来一天 96 点递推预测
- 同时段 7 天中位数 + 稳健 3σ 异常检测
- Flask REST API + SQLite 存储
- ECharts 看板：趋势、排名、预测对比、异常清单
- 一键启动脚本 `start.bat`

## 3. 技术栈

| 层次 | 技术 |
|---|---|
| 后端 | Python 3.10+、Flask |
| 数据库 | SQLite（Python 标准库 `sqlite3`） |
| 数据分析 | pandas、numpy |
| 机器学习 | scikit-learn（RandomForestRegressor） |
| 前端 | HTML、CSS、原生 JavaScript、ECharts |
| 工程 | Git、requirements.txt、start.bat |

## 4. 系统架构

```text
data/generate_data.py
        │  生成 CSV
        ▼
scripts/init_db.py ──────► SQLite（grid.db）
        │                     │
        │                     ├── load_data       负荷明细
        │                     ├── forecasts       预测结果
        │                     ├── anomalies       异常清单
        │                     └── model_metrics   模型指标
        │
        ▼
ml/train.py
  特征工程 → 随机森林 → 评估 → 保存模型 / 写预测结果

ml/anomaly.py
  同时段中位数 → 残差 → 稳健 3σ → 写异常清单

app.py（Flask）
  REST API ──────► templates/index.html + static/js/dashboard.js
                              │
                              ▼
                         ECharts 看板
```

## 5. 最快启动（Windows，推荐零基础）

### 第一步：安装 Python

安装 **Python 3.10 或更高版本**：<https://www.python.org/downloads/>

安装时务必勾选：

- [x] Add Python to PATH

安装完成后，打开命令提示符，输入：

```bat
python --version
```

能显示版本号即可。

### 第二步：双击 `start.bat`

脚本会自动完成：

1. 检查系统 Python 和依赖（缺了才安装）
2. 生成模拟数据
3. 初始化数据库
4. 训练模型
5. 检测异常
6. 启动网站

如果依赖已经安装，几秒就能启动；缺依赖时才需要下载，通常 2–5 分钟。  
看到下面的提示后，在浏览器打开：

```text
http://127.0.0.1:5000
```

停止服务：在命令行窗口按 `Ctrl + C`。

> `start.bat` 的提示使用英文，是为了避免 Windows 命令行对中文批处理的编码问题；网页、代码注释和文档仍然是中文。  
> 如果 `start.bat` 一闪而过，先检查 Python 是否装好：在命令行执行 `python --version`。

## 6. 手动运行（想练习虚拟环境时用）

`start.bat` 为了简单，直接使用系统 Python，不创建虚拟环境。  
如果你想练习“创建独立环境”，可以按下面的步骤手动执行：

在项目根目录打开 PowerShell 或命令提示符，依次执行：

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python data\generate_data.py
python scripts\init_db.py
python ml\train.py
python ml\anomaly.py
python app.py
```

每一步的作用：

| 命令 | 作用 |
|---|---|
| `generate_data.py` | 生成 `data/load_data.csv` 和 `data/districts.csv` |
| `init_db.py` | 建表并把 CSV 导入 `data/grid.db` |
| `train.py` | 训练模型，写 `models/` 和 `forecasts` 表 |
| `anomaly.py` | 检测异常，写 `anomalies` 表 |
| `app.py` | 启动 Flask 网站 |

## 7. 数据说明

项目使用 **模拟数据**，不包含任何真实用户信息。

| 字段 | 含义 |
|---|---|
| `district_id` | 台区编号 |
| `date` | 日期 |
| `time_index` | 0–95，每 15 分钟一个点 |
| `load_kw` | 负荷，单位 kW |
| `temperature` | 温度 |
| `is_holiday` | 是否节假日 |
| `is_injected_anomaly` | 是否为人为注入的异常（仅用于评估） |

数据生成时故意加入：

- 少量缺失值
- 30 行重复数据
- 332 行注入异常（持续偏高/偏低 + 单点尖峰/骤降）

> 真实台区数据涉及用户隐私，学生项目一般拿不到。  
> 用模拟数据做方法验证是合理的，但简历和面试中必须说明“模拟数据”，不要写成“国家电网真实数据”。

## 8. 模型方法

### 8.1 负荷预测

**任务**：给定历史 96 点负荷，预测未来一天 96 点负荷。

**特征**：

- 时刻 `time_index`、小时 `hour`
- 星期 `weekday`、是否周末 `is_weekend`
- 温度 `temperature`
- 昨天同一时刻负荷 `lag_1d`
- 上周同一时刻负荷 `lag_7d`
- 上一个 15 分钟负荷 `prev_load`
- 最近 1 小时滑动平均 `rolling_mean_4`
- 最近 1 天滑动平均 `rolling_mean_96`

**模型**：每个台区单独训练一个 `RandomForestRegressor`。

**为什么不用 LSTM？**

- 数据量只有约 2.8 万条，LSTM 容易过拟合；
- 表格特征下随机森林训练快、可解释、调参少；
- 校招项目更重要的是“评估严谨、能讲清楚”，不是模型越深越好。

**防止数据泄漏**：

- 按时间切分：前 50 天训练，后 10 天测试；
- 滞后特征只使用预测时点之前的数据；
- 不用随机打乱的方式切分时间序列。

**未来一天预测**：

- 00:00 的“上一个 15 分钟”是最后一天 23:45，已知；
- 00:15 之后使用模型刚刚预测出的值，属于递推预测；
- 递推误差会累积，这是项目的一个已知局限。

### 8.2 异常检测

**思路**：

1. 对每个台区、每个时刻，取过去 7 天同一时刻负荷的**中位数**作为期望值；
2. 计算实际值与期望值的残差；
3. 用 **MAD** 估计稳健标准差，计算稳健 Z 分数；
4. 同时满足 `|Z| >= 4.5` 且 `|偏差| >= 20%` 才标记为异常。

**为什么用中位数和 MAD？**

- 中位数不受极端值影响；
- MAD 比标准差更不容易被异常点“带偏”；
- 规则简单，面试时容易解释，也方便后续替换成 Isolation Forest。

**注意**：异常检测的结果是“疑似清单”，不是直接认定窃电，最终需要业务人员复核。

## 9. 当前运行结果

### 9.1 预测指标

| 指标 | 结果 |
|---|---|
| 数据规模 | 5 个台区 × 60 天 × 96 点，去重后 28,800 条 |
| 训练/测试 | 前 50 天训练，后 10 天测试 |
| 模型 | 每个台区独立随机森林（200 棵树） |
| 测试集 MAE | **12.83 kW** |
| 测试集 MAPE | **4.01%** |
| 基线 MAPE（昨天同时刻） | **7.11%** |
| MAPE 降低 | 约 **3.10 个百分点**（相对降低约 43.6%） |

分台区结果：

| 台区 | MAE | MAPE | 基线 MAPE |
|---|---:|---:|---:|
| 滨河小区台区 | 10.38 kW | 4.09% | 8.79% |
| 高新产业园台区 | 15.74 kW | 3.03% | 6.87% |
| 中心商业街台区 | 13.40 kW | 3.53% | 5.20% |
| 大学城台区 | 16.96 kW | 5.97% | 9.29% |
| 城郊安置区台区 | 7.64 kW | 3.41% | 5.42% |

### 9.2 异常检测指标

| 指标 | 结果 |
|---|---|
| 告警数量 | 361 |
| 可评估的注入异常 | 288 |
| TP / FP / FN | 288 / 73 / 0 |
| 精确率 | **79.78%** |
| 召回率 | **100%** |
| F1 | **88.75%** |

> 召回率 100% 是因为模拟数据中的异常注入得比较明显，且评估只统计“期望值可计算”的异常点。  
> 真实数据中指标通常会下降，面试时主动说明这一点，比硬说“100% 准确”更可信。

## 10. 项目结构

```text
grid-load-forecast/
├─ app.py                    # Flask 入口和 REST API
├─ start.bat                 # Windows 一键启动
├─ requirements.txt
├─ data/
│  ├─ generate_data.py       # 模拟数据生成
│  ├─ districts.csv          # 台区档案（生成）
│  ├─ load_data.csv          # 负荷明细（生成）
│  └─ grid.db                # SQLite 数据库（生成）
├─ scripts/
│  └─ init_db.py             # 建表 + 导入 CSV
├─ ml/
│  ├─ train.py               # 特征工程 + 训练 + 评估 + 预测
│  └─ anomaly.py             # 异常检测 + 评估
├─ models/
│  ├─ forecast_models.joblib # 每个台区一个模型（生成）
│  ├─ metrics.json           # 预测指标（生成）
│  └─ anomaly_metrics.json   # 异常指标（生成）
├─ templates/
│  ├─ base.html
│  └─ index.html
├─ static/
│  ├─ css/style.css
│  └─ js/dashboard.js
└─ docs/
   └─ 学习与面试指南.md
```

## 11. API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/districts` | 台区列表 |
| GET | `/api/overview?district_id=1` | 当日 KPI、异常数、模型指标 |
| GET | `/api/load?district_id=1&days=7` | 近 7 天日平均/日最大负荷 |
| GET | `/api/forecast?district_id=1` | 测试日实际 vs 预测、下一天预测 |
| GET | `/api/anomalies?district_id=1&limit=30` | 异常清单 |
| GET | `/api/ranking` | 当日各台区用电量排名 |
| GET | `/api/metrics?district_id=1` | 预测与异常指标 |


**当前不足**：

- 数据是模拟的，不能代表真实台区；
- SQLite 只适合单机演示，没有并发和权限设计；
- 没有实时数据接入，预测是离线批量生成的；
- 异常检测规则较简单，真实场景误报会更多；
- 递推预测存在误差累积；
- 没有做更细的超参数搜索和模型监控。

**后续可以怎么改**：

- 接入真实负荷/气象数据，换成 MySQL/PostgreSQL；
- 增加节假日、电价、用户类型等特征；
- 对比 LightGBM、Prophet、LSTM；
- 加定时任务，每天自动重训和预测；
- 加登录、角色权限、告警推送；
- 用 Docker 部署到云服务器。

## 12. 声明

- 本项目仅用于学习、校招展示和方法验证。
- 数据为程序模拟生成，不代表任何真实电网、台区或用户。
- 异常检测结果仅作为筛查参考，不能作为认定窃电的依据。
