# 数据字典、参数口径与输出说明

## 1. 数据版本与用途

本项目使用冻结的 Yahoo Finance Chart 响应重建三只标的股票的数据，并将合同履约回放与模型参数估计分开处理。

- 股票：AMZN、NVDA、PLTR；
- 原始请求区间：2025-01-01 至 2026-11-06；
- 有效交易日区间：2025-01-02 至 2026-11-06；
- 冻结快照下载日：2026-11-09；
- 每只股票有效交易日：464；
- 产品定价日：2025-12-19；
- 发行日模型与主数据质量档案截止日：2026-11-06；
- 合同回放与历史图的当前 Close 增量截止日：2026-11-20。

定价日模型只使用截至 2025-12-19 的信息估计参数。主 Yahoo Finance 档案保持冻结至2026年11月6日；程序从 `data/stress/raw/` 读取单独验证的当前 Close 快照，把合同回放和历史图延伸至2026年11月20日。所有定价日后的真实价格均不进入定价日模型校准，以避免前视偏差。

---

## 2. 原始数据

### 2.1 `raw/manifest.json`

记录以下可追溯信息：

- 数据提供方；
- 原始请求起止时间；
- 数据下载日期；
- 每只股票的精确请求 URL；
- 每份原始 JSON 的 SHA-256 校验值。

程序每次运行都会重新计算原始文件的 SHA-256。如果文件与 manifest 不一致，数据处理将停止。

### 2.2 `raw/AMZN.json`、`raw/NVDA.json`、`raw/PLTR.json`

Yahoo Finance Chart API 的冻结响应，主要使用：

| 原始字段 | 单位与频率 | 用途 |
|---|---|---|
| `timestamp` | Unix 秒，每个交易日 | 转换为 America/New_York 当地交易日期 |
| `quote.close` | USD/股，日频 | 重建合同使用的 Close |
| `adjclose.adjclose` | USD/股，日频 | 重建用于历史参数估计的 Adjusted Close |
| `events.dividends` | USD/股 | 记录现金分红 |
| `events.splits` | 拆股比例 | 检测公司行动和潜在合同调整 |
| `meta.symbol` | 股票代码 | 验证标的身份 |
| `meta.currency` | 币种 | 必须为 USD |
| `meta.exchangeTimezoneName` | 时区 | 必须为 America/New_York |

---

## 3. 处理后数据

### 3.1 `processed/prices_close.csv`

| 字段 | 类型与单位 | 说明 |
|---|---|---|
| `date` | ISO 日期 | 美国市场交易日 |
| `AMZN`、`NVDA`、`PLTR` | USD/股 | Yahoo Close，输出至小数点后两位 |

主要用途：

- 按合同观察日回放实际票息和赎回状态；
- 与合同列示的美元障碍价格比较；
- 绘制历史标准化价格图。

合同履约判断使用 Close，而不是 Adjusted Close。程序会核对定价日 Close 与合同初始价格是否完全一致。

### 3.2 `processed/prices_adjusted.csv`

| 字段 | 类型与单位 | 说明 |
|---|---|---|
| `date` | ISO 日期 | 美国市场交易日 |
| `AMZN`、`NVDA`、`PLTR` | USD/股 | 供应商 Adjusted Close，保留六位小数 |

主要用途：

- 计算日对数收益率；
- 估计年化波动率；
- 估计收益率相关矩阵。

Adjusted Close 用于消除分红和拆股对历史收益率造成的非经济性跳变，不能直接与合同原始美元障碍比较。

### 3.3 `processed/prices_close_replay.csv`

该文件由程序运行时生成，包含 `prices_close.csv` 的主档案以及 `data/stress/raw/` 中主档案截止日之后的共同交易日 Close。当前版本增加2026年11月9日至11月20日十个交易日，共474个日期。它只用于合同历史回放与 `normalized_prices.svg`，不用于发行日波动率、相关性或估值参数校准。

### 3.4 `processed/corporate_actions.csv`

| 字段 | 类型与单位 | 说明 |
|---|---|---|
| `date` | ISO 日期 | 公司行动日期 |
| `symbol` | 股票代码 | AMZN、NVDA 或 PLTR |
| `event` | 文本 | `dividends` 或 `splits` |
| `value` | USD/股或比例 | 分红金额或拆股比例 |

当前窗口记录 NVDA 七笔现金分红，三只股票均无拆股记录。若检测到拆股，程序会停止自动回放，要求核对计算代理的合同调整。

### 3.5 质量检查结果

`output/tables/data_quality.csv` 每只股票一行，包含：

- 首末交易日；
- 交易日数量；
- 缺失交易日；
- 重复日期；
- 缺失价格；
- 拆股和分红数量；
- 定价日 Close；
- 合同初始价格。

当前三只股票均有 464 个交易日，缺失、重复和非法价格数量均为零，定价日 Close 与合同初始价格一致。

---

## 4. 市场日历

### `config/market_calendar.yaml`

保存项目使用的交易日区间和特殊休市日期。周末和全日休市日从预期交易日中剔除，提前收市日仍计为交易日。

日历参考：

- [Nasdaq Trader Calendar](https://www.nasdaqtrader.com/Trader.aspx?id=Calendar)；
- [2025-01-09 特别休市公告](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-1)。

程序要求三只股票的实际日期集合与预期交易日集合完全一致，不进行自动插值或向前填充。

---

## 5. 合同与模型配置

### 5.1 `config/product_terms.yaml`

保存 SEC 最终定价文件确定的合同参数：

- 产品名称、ISIN、CUSIP、发行人和币种；
- 面值、定价日、结算日和到期日；
- 年化票息率和每年票息次数；
- Memory coupon 开关；
- 三只股票的初始价格、票息障碍和本金障碍；
- 自动赎回起始期及赎回水平；
- Best-of 本金保护开关和保护水平；
- 12 组观察日与付款日。

金额以每张面值 USD 1,000 的票据为单位。程序使用合同列示的实际障碍价格，不以未经舍入的 50% 计算值替代。

### 5.2 `config/model_inputs.yaml`

| 参数 | 当前值或单位 | 用途 |
|---|---|---|
| `model` | `correlated_gbm` | 相关几何布朗运动 |
| `measure` | `risk_neutral` | 风险中性估值口径 |
| `risk_free_rate` | 0.0353 | 常数连续复利无风险利率近似 |
| `dividend_yields` | AMZN 0；NVDA 0.0003；PLTR 0 | 连续股息率假设 |
| `volatilities` | 年化小数 | 一年历史窗口估计 |
| `correlation` | 无量纲矩阵 | 一年历史窗口日对数收益相关性 |
| `n_paths` | 100000 | Monte Carlo 路径数 |
| `seed` | 5690 | 固定随机种子，保证复现 |

无风险利率当前以定价日附近三年期美国国债收益率 3.53% 作常数连续利率近似。股息率为当前模型简化假设。正式提交前应由模型负责人确认利率曲线、计息约定和股息率依据，并将对应来源或假设说明加入 Source Table；这些值不是 SEC 合同参数。

---

## 6. 参数估计

### 6.1 收益率

使用 Adjusted Close 的日对数收益：

\[
r_{i,t}=\ln\left(\frac{S^{adj}_{i,t}}{S^{adj}_{i,t-1}}\right).
\]

### 6.2 年化波动率

使用样本标准差并按 252 个交易日年化：

\[
\sigma_i=\operatorname{Std}(r_{i,t})\sqrt{252}.
\]

### 6.3 相关矩阵

使用同一窗口内三只股票日对数收益的 Pearson 相关系数。

### 6.4 估计窗口

| 窗口 | 起止日期 | 日收益数 | 用途 |
|---|---|---:|---|
| 一年窗口 | 2025-01-02 至 2025-12-19 | 242 | 历史基准参数 |
| 半年窗口 | 2025-06-19 至 2025-12-19 | 127 | 参数窗口敏感性 |

具体波动率和相关系数保存在 `output/tables/parameters.csv`。模型时间间隔和现金流折现使用 Actual/365；历史波动率年化使用 252 个交易日，二者用途不同。

---

## 7. 输出表格

### 7.1 `output/tables/historical_replay.csv`

定价日后的实际合同回放，每行对应一个已发生观察日：

| 字段 | 含义 |
|---|---|
| `period` | 观察期编号 |
| `observation_date`、`payment_date` | 观察日和相关付款日 |
| `AMZN`、`NVDA`、`PLTR` | 观察日实际 Close，USD/股 |
| `coupon` | 当期实际支付票息，包括 Memory 补发 |
| `pending_periods` | 尚待恢复的票息期数 |
| `expired_periods` | 到期失效的未付票息期数 |
| `principal` | 当期偿还本金 |
| `cashflow` | 票息与本金之和 |
| `status` | `outstanding`、`autocalled` 或 `matured` |

### 7.2 `output/tables/parameters.csv`

记录一年和半年估计窗口的：

- 样本起止日期；
- 日收益数量；
- 三只股票年化波动率；
- 三组两两相关系数。

### 7.3 `output/tables/monte_carlo_summary.csv`

记录历史基准情景的主要估值和风险指标：

- 模型、路径数、随机种子和无风险利率；
- 模型价值和 Monte Carlo 标准误；
- 未折现预期现金流；
- 自动赎回、本金损失及负回报比例；
- 平均票息；
- 平均、中位数和第 5 百分位名义回报；
- 最差 5% 路径平均回报；
- 平均本金支付时间；
- Memory 补发比例；
- 路径现值的最小值、分位数和最大值。

所有概率和分布均来自风险中性模型，不能解释为现实世界预测概率。

### 7.4 `output/tables/scenarios.csv`

每行对应一组情景，包含模型价值、标准误、赎回比例、本金损失比例、负回报比例、平均票息、回报分位数、尾部回报、平均期限和 Memory 补发比例。

当前十组情景包括：

1. 开发期参数；
2. 仅替换 PLTR 波动率；
3. 一年历史参数基准；
4. 半年历史窗口；
5. 全部波动率增加 25%；
6. 较低相关性；
7. 较高相关性；
8. 高波动率与低相关性组合；
9. 取消 Memory coupon；
10. 取消 Best-of 本金保护。

### 7.5 `output/tables/exit_distribution.csv`

记录每个情景、每个观察期的无条件自动赎回比例和到期退出比例。各期退出比例之和为 1。

### 7.6 `output/tables/representative_median_path.csv`

记录从全部 Monte Carlo 路径中选出的代表性实际路径及其逐期现金流。该路径最接近逐观察日、逐标的标准化价格的横截面中位数，但不等于预期路径或最可能路径。

---

## 8. 输出图形

`output/figures/` 当前包含：

| 文件 | 内容 |
|---|---|
| `normalized_prices.svg` | 定价日后的真实标准化 Close、障碍和观察日；当前展示截止2026-11-20 |
| `maturity_redemption_map.svg` | Worst-of 与 Best-of 共同决定的到期本金状态图 |
| `monte_carlo_value_distribution.svg` | 折现路径价值分布及三项价格参照 |
| `nominal_return_distribution.svg` | 风险中性名义总回报及最差 5% 尾部 |
| `exit_distribution.svg` | 各观察期自动赎回、到期和累计赎回比例 |
| `coupon_distribution.svg` | 最终实际支付票息期数分布 |
| `scenario_sensitivity.svg` | 各情景相对历史基准的模型价值变化 |
| `parameter_window_comparison.svg` | 一年与半年窗口波动率及模型价值比较 |
| `correlation_heatmap.svg` | 一年与半年窗口相关矩阵比较 |
| `representative_median_path.svg` | 代表性实际模拟路径及合同状态 |
| `monte_carlo_paths.svg` | 相关 GBM 路径样本和中位走势 |

图形的详细阅读方法见项目根目录 `FIGURE_GUIDE.md`。

---

## 9. 数据与模型验证

`src/data_loader.py` 执行：

- 原始文件 SHA-256 校验；
- 股票代码、币种和时区校验；
- 交易日集合匹配；
- 重复日期、缺失值、非正数和非有限价格检查；
- 定价日 Close 与合同初始价格核对；
- 拆股检测。

`tests/` 当前包含 18 项自动测试，覆盖：

- 第一观察日不可自动赎回；
- 首个符合资格的观察日赎回；
- Memory 累计、补发和重置；
- 提前赎回后后续现金流为零；
- 到期 Worst-of 本金损失；
- Best-of 本金保护及等号边界；
- 合同列示障碍边界；
- 向量化现金流与可读单路径引擎一致；
- 固定随机种子的可复现性；
- 模拟价格形状和正值；
- 零波动率确定性增长；
- 相关矩阵有效性；
- 历史校准结果；
- 折现估值；
- 退出分布合计为 1。

自动测试是当前主要验证证据。组内可由非主要实现者复核边界案例和预期结果，无需为满足课程要求另建重复的计算引擎。

---

## 10. 复现方法

从项目根目录运行：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.demo
python -m src.stress_demo
```

依赖版本：

- Python 3.10；
- PyYAML 6.0；
- reportlab 3.6.12；
- NumPy 1.26.4。

只要原始数据、配置、依赖和随机种子保持不变，主要表格、图形和终端摘要应可重复生成。

### 10.1 Terminal 摘要与底层表格的对应关系

`python -m src.demo` 的发行日估值和敏感性摘要分别来自：

- `monte_carlo_summary.csv`；
- `scenarios.csv`；
- `historical_replay.csv`。

`python -m src.stress_demo` 的七段当前状态摘要分别来自：

- 当前状态：`stress_current_state.csv`；
- 选定诊断分界点前后比较：`election_pre_post_comparison.csv`；
- 参数更新：`election_regime_parameters.csv`；
- 事件研究：`spacex_event_study.csv`；
- 五情景结果：`stress_scenarios.csv`；
- 非线性互动：`interaction_decomposition.csv`。

Terminal 只负责便于快速阅读，不替代 CSV。报告数字应优先引用对应 CSV，以保留完整精度和可审计性。

---

## 11. 当前状态压力测试扩展数据

### 11.1 `event_study/raw/`

保存 AMZN、NVDA、PLTR、QQQ 和 SOXX 的 Nasdaq 历史行情冻结响应，覆盖 SpaceX 2026-06-12 IPO 的估计窗口和事件窗口。`manifest.json` 保存每份快照的 SHA-256，程序运行时重新验证。

### 11.2 `event_study/processed/event_prices.csv`

五个代码按共同交易日对齐后的收盘价宽表。该数据只用于 SpaceX IPO 事件研究，不进入发行日参数校准。

### 11.3 `stress/raw/`

保存 AMZN、NVDA 和 PLTR 截至 2026-11-20 的冻结快照，用于确定当前状态估值的起始价格，并与长期 Adjusted Close 合并以估计近期 EWMA 参数。主档案截止日之后的共同 Close 也用于延伸合同回放与历史图。2026-10-15至2026-11-19的原始区间来自 Nasdaq 历史接口；2026-11-20一行来自 Yahoo Finance 历史价格页，并在 `manifest.json` 中单独记录来源、抓取日期和更新后的 SHA-256。该扩展不会改写合同初始价格、障碍价格、自动赎回水平或发行日校准参数。

### 11.4 `rates/treasury_curve_2026-11-19.csv`

| 字段 | 说明 |
|---|---|
| `as_of` | Federal Reserve H.15 数据日期 |
| `tenor_years` | 期限，以年表示 |
| `zero_rate` | 年化小数；课堂模型将 constant-maturity yield 作为连续复利零息率代理 |
| `source` | 数据来源 |
| `interpretation` | 模型解释和限制 |

该曲线用于当前压力估值中的路径远期利率和现金流贴现。它不是交易级 OIS 零息曲线，因此只能解释为透明、可复现的利率期限结构代理。
2026-11-21提交版本使用美联储2026-11-20发布的 [H.15 Selected Interest Rates](https://www.federalreserve.gov/releases/h15/)；该期最新可用的 constant-maturity 观察日为2026-11-19。

### 11.5 当前状态、参数换挡和事件输出

`output/stress/tables/` 包含：

- `spacex_event_study.csv`：事件窗口、原始收益、CAR、近似 z 值和回归系数；
- `stress_current_state.csv`：估值日价格、假设性共同股票冲击及其历史幅度来源；字段名为兼容既有输出保留；
- `election_pre_post_comparison.csv`：2026-11-03 这一选定分界点前后等长窗口的累计收益和已实现波动率；文件名仅为兼容既有输出，不代表因果识别；
- `election_regime_parameters.csv`：长期、EWMA、收缩后当前参数以及分界点前后诊断估计；
- `stress_scenarios.csv`：旧参数基准、当前参数基准及四个 2×2 因子情景的估值与风险指标；
- `stress_exit_distribution.csv`：五个当前状态情景的剩余观察期退出概率；
- `interaction_decomposition.csv`：联合结果相对机械可加预测的互动项。

2026-11-03 只作为描述性参数窗口边界，不代表政治事件产生可识别影响，也不是第二次价格冲击。SpaceX CAR 只为假设性共同股票冲击提供历史幅度参照；SpaceX 并非直接可比公司，单一事件 CAR 不构成因果证明、现实世界发生概率或未来收益预测。所有当前压力概率仍为风险中性模型结果。

---

## 12. 已知数据与参数限制

- Yahoo Finance 是公共市场数据源，不是合同指定的计算代理数据源；
- 历史波动率和相关性可能随样本窗口变化；
- 分界点后的诊断窗口只有 13 个日收益，近期相关性因此向长期矩阵收缩，但参数不确定性仍然较高；
- 发行日模型使用单一常数利率；当前压力扩展将 H.15 constant-maturity yields 作为零息曲线代理，而非交易级 OIS 曲线；
- 当前股息率为简化假设，未建立期限结构；
- 历史参数不是期权市场隐含参数；
- 风险中性概率不是投资者现实世界发生概率；
- 当前模型不包含跳跃、随机波动率、动态相关性、发行人违约、bail-in 或二级市场流动性；
- 市场中断、延期估值和计算代理裁量不在普通计划内模拟中自动处理；
- 定价日后的真实行情只能用于履约回放，不应进入定价日参数估计。
