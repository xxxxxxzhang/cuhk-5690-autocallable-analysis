# 数据字典与来源

快照取于 2026-11-09，窗口为 2025-01-01 至 2026-11-06，首个交易日为 2025-01-02。每只股票保留独立的 Yahoo Finance Chart 原始 JSON。精确请求、校验值和更新时间见 [manifest](raw/manifest.json)。冻结快照以便复现，重新采集时另存版本并重新检查公司行动。

| 文件 / 字段 | 单位、频率与用途 | 来源和处理 |
| --- | --- | --- |
| raw/*.json 的 timestamp、quote.close | Unix 秒、美元/股，每个交易日 | 以 America/New_York 得交易日；检查代码、币种、时区和重复日期。 |
| processed/prices_close.csv 的 date、AMZN、NVDA、PLTR | ISO 交易日、美元/股；合同回放、价格走势图 | Yahoo 的 close 按拆股口径呈现；本窗口事件字段无拆股。保留原始值，输出四舍五入至美分以消除二进制报价噪声。定价日与合同初始价逐股核对。 |
| processed/prices_adjusted.csv 的三列股票 | 美元/股、日频；候选历史收益输入 | 供应商调整收盘价，包含其拆分、分红调整，保留六位小数。成员 B 确认历史收益口径与回看窗口。 |
| processed/corporate_actions.csv 的 date、symbol、event、value | 除权息日、股票代码；dividends 为美元/股，splits 为比例 | 原始 events 字段。窗口内返回 NVDA 7 笔现金分红，三股均无拆股记录；发生拆股时回放会暂停，需核对计算代理调整。 |
| output/tables/data_quality.csv | 每只标的 1 行 | 按日历逐日匹配、查重、校验两个价格字段；缺失记录、非法价格或合同初值不符均报错，无插值。 |
| config/product_terms.yaml | 单张票据美元金额、比率、ISO 日期 | SEC 定价文件 PS-1、PS-2，成员 A 待复核。schedule 每对日期依次为观察日与支付日。 |
| 两张现金流表的 period、observation_date、payment_date、股票代码 | 观察期、计划日期、各股美元收盘价 | historical_replay 使用行情；synthetic_memory_call 使用手设路径。 |
| coupon、principal、cashflow | 每张票据应付美元 | 含补发的票息、当期偿还本金、二者之和。保留合同票息精度。 |
| pending_periods、expired_periods、status | 期数、期数、状态 | 期末可补发期数、到期失效期数、outstanding / autocalled / matured。 |

周末和全日休市日从预期交易日中剔除；提前收市日计入。2025-01-09 特别休市也已纳入。[Nasdaq 交易日历](https://www.nasdaqtrader.com/Trader.aspx?id=Calendar) · [特别休市公告](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-1)

| 后续输入 | 负责人及待定口径 |
| --- | --- |
| 股息、波动率、相关系数 | B 选择历史/隐含估计、期限、样本区间及分红预测。C 按估值日截断，并记录数据版本。 |
| 无风险利率、折现和发行人信用 | B 确认曲线、计息约定和是否计入发行人信用。A 整理 Barclays 发行文件和信用资料。 |
| 历史与模拟 | 定价日估值仅使用当时可知的输入。快照中的后续价格用于回放；如要求严格时点数据，还需取得当时留存的行情/参数版本。 |
