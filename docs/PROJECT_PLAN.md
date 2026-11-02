# 量化交易系统 — 架构评估与项目计划

> 版本 v0.1 · 2026-10-31
>
> **已确认基线：加密货币 · 分钟级 · 单人业余。**
> 可执行版本见 [`PLAN_V1.md`](./PLAN_V1.md)（含简化后的技术栈与 20 周计划）；本文档保留为通用架构参考。

---

## 1. 结论先行

你提出的分层：

```
Web 后台  →  Go 后端  →  MySQL / Redis
                 ↕
             Python（采集 / 策略 / 交易）
```

**方向是对的**，选择 Go 做业务 API、Python 做量化计算是业界常见组合（Python 生态有 pandas / polars / ccxt / vnpy，Go 适合写稳定的 API 和并发服务）。

但有 4 个必须修正的设计点：

| # | 问题 | 修正 |
|---|---|---|
| 1 | **Go 与 Python 之间用 HTTP 互相调用**会形成双向依赖，Python 挂了 Web 就会卡死 | 拆成**控制面**和**数据面**：控制面用 gRPC（Go 是 server，Python 是 client）；数据面用 Redis Stream，双方只读写流，不直接调用 |
| 2 | **Python 一个进程干采集+策略+交易**，策略代码崩溃会连带丢掉行情和订单 | 拆成 4 类独立进程，各自可独立重启：Collector / Strategy / OMS(交易执行) / Watchdog |
| 3 | **MySQL 存 tick / 分钟 K 线**，写入量和范围扫描都扛不住，且回测会拖垮业务库 | 业务数据（订单、持仓、配置、审计）进 MySQL；**行情原始数据进 Parquet + ClickHouse**，Redis 只做缓存和消息流 |
| 4 | 缺少**订单状态机 + 对账 + 独立风控**，这是量化系统唯一真正会亏钱的地方 | OMS 作为订单唯一事实源，状态只由交易所回报驱动；每日自动对账；pre-trade 风控独立于策略代码 |

另外补一句：**不要让 Web 后台成为交易链路的一环**。后台是“观测 + 配置”端，链路断开时策略必须能自主运行。

---

## 2. 目标架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Web 前端 (React/Vue + TS + TradingView lightweight-charts)      │
└───────────────┬──────────────────────────────────────────────────┘
                │ HTTPS / WebSocket
┌───────────────▼──────────────────────────────────────────────────┐
│  Go 服务层  (gin/echo)                                            │
│  ├─ Auth / RBAC / 审计                                            │
│  ├─ 策略管理 / 参数下发 / 启停                                     │
│  ├─ 订单·持仓·盈亏查询                                             │
│  ├─ 回测任务提交与报告                                             │
│  ├─ WebSocket 实时推送（订阅 Redis Stream → 前端）                 │
│  └─ gRPC Server（控制面：Agent 注册、心跳、指令下发）               │
└───────┬───────────────────────────────┬──────────────────────────┘
        │ SQL                           │ 只读 Stream / 也可写指令流
┌───────▼────────┐            ┌─────────▼──────────────────────────┐
│ MySQL 8        │            │ Redis 7                            │
│ 业务事实数据    │            │ 缓存 / 分布式锁 / Stream 消息总线   │
└────────────────┘            └─────────┬──────────────────────────┘
                                        │ md.tick / sig / order.events
┌───────────────────────────────────────▼──────────────────────────┐
│  Python 交易集群（每个策略实例独立容器/进程）                       │
│                                                                  │
│  ① Collector      行情采集 → 清洗 → Parquet/MinIO → ClickHouse    │
│  ② Strategy       ClickHouse/Stream 读行情 → 计算 → 发 signal     │
│  ③ OMS            消费 signal → 风控 → 下单 → 回报 → MySQL + 流   │
│  ④ Recon          每日对账（持仓/余额/成交）                       │
│  ⑤ Watchdog       心跳、行情断流、持仓漂移检测，异常可全局熔断      │
└──────────────────────────────────────────────────────────────────┘
```

### 职责边界（重要，写进代码规范）

| 组件 | 负责 | **不负责** |
|---|---|---|
| Go | 用户、权限、配置、查询、展示、指令下发、审计 | 不计算行情、不撮合、不下单 |
| Collector | 采集、去重、补缺、标准化、落盘 | 不做策略 |
| Strategy | 读数据、出信号（纯函数式，无 IO 副作用） | 不直接下单、不碰账户 |
| OMS | 订单生命周期、风控、与券商交互、回报落库 | 不含任何策略逻辑 |
| MySQL | 订单/成交/持仓/配置/审计的唯一事实源 | 不存高频行情 |
| Redis | 缓存、锁、消息流、实时快照 | **不作为订单状态的唯一存储** |

---

## 3. 技术选型

> 本节是**通用备选**，用于解释取舍。本仓库 V1 的实际选择以 [`PLAN_V1.md`](./PLAN_V1.md) §8 为准
> （Vue 3 + Element Plus、gin + slog + `database/sql`、Parquet + DuckDB 等）。

| 层 | 推荐 | 备选 / 说明 |
|---|---|---|
| Web 前端 | React + TS + Vite + Ant Design + ECharts / lightweight-charts | Vue3 亦可；图表别自己写 |
| Go Web | gin + sqlc（或 gorm）+ zap + viper | sqlc 生成类型安全 SQL，比 ORM 可控 |
| Go 控制面 | gRPC + protobuf | 一次定义契约，Python/Go 都生成代码 |
| Python | 3.11+，uv 管理依赖，pydantic v2，polars | 策略热路径避免 pandas 的隐式拷贝 |
| 数据采集 | 按市场选：ccxt(crypto) / vnpy-CTP(期货) / 券商柜台 API / Tushare/AkShare(日线) | 采集器要支持断点续采 |
| 时序存储 | ClickHouse（推荐）或 TimescaleDB | 初期可 Parquet + DuckDB 过渡，接口抽象好再换 |
| 对象存储 | MinIO（本地 S3）存原始 tick / 回放数据 | 回测和复盘都靠它 |
| 消息 | Redis Stream（Consumer Group） | 量大再换 NATS JetStream / Kafka |
| 容器 | docker-compose 起步 → k8s | 不要一开始上微服务 |
| 监控 | Prometheus + Grafana + Loki | 必须有的告警：订单被拒、行情断流、持仓不一致、策略掉线 |

---

## 4. 关键设计决策

### 4.1 控制面 vs 数据面

- **控制面（低频、要可靠）**：gRPC。Python Agent 启动后向 Go 注册并每 5s 心跳；Go 下发 `StartStrategy / StopStrategy / UpdateParams / FlattenAll`。
- **数据面（高频、可丢可重放）**：Redis Stream。
  - `md.tick`（行情，可按 symbol 分片）
  - `sig.{strategy_id}`（信号）
  - `order.events`（订单回报，OMS 写，Go 读后推 WebSocket）
- Python 进程**只作为 client**，Go 不主动连 Python，避免网络拓扑双向耦合。

### 4.2 订单状态机（最容易出 bug 的地方）

```
PENDING_NEW → SUBMITTED → PARTIAL → FILLED
                    ↓         ↓
                CANCELED   CANCELED
                    ↓
                REJECTED / EXPIRED
```

规则：
- 状态**只能单向前进**，禁止回退；
- 用 `client_order_id` 唯一索引做幂等，重试不会重复下单；
- 每次回报以 `(broker, account, exchange_order_id)` 做 upsert；
- 下单前先落 `PENDING_NEW`，**先写库再发请求**，崩溃后能恢复；
- 启动时执行一次“挂单恢复”：拉交易所未结订单与本地比对。

### 4.3 回测与实盘共用一套策略代码

定义唯一的策略接口：

```python
class Strategy(Protocol):
    def on_start(self, ctx: Context) -> None: ...
    def on_bar(self, ctx: Context, bar: Bar) -> None: ...
    def on_tick(self, ctx: Context, tick: Tick) -> None: ...
    def on_order(self, ctx: Context, evt: OrderEvent) -> None: ...
    def on_stop(self, ctx: Context) -> None: ...
```

回测只是换掉 `Context` 的 `Broker` 和 `Clock` 实现（回放 Broker / 实时 Broker）。
**同一个策略在回测和实盘中走完全相同的代码路径**，否则回测结论无效。

### 4.4 撮合模拟必须贴近现实

- 手续费、印花税、过户费（按市场）、最小变动价位；
- 滑点模型（固定 / 按波动率 / 按订单簿深度）；
- 涨跌停、停牌、T+1（A股）、集合竞价；
- **成交量约束**：单笔成交量不超过该 bar 成交量的 X%，否则按比例成交 —— 这一条决定回测收益是否真实；
- 资金占用与保证金计算。

### 4.5 独立风控（Pre-trade Risk）

风控是**库**，被 OMS 同步调用（微秒级），配置来自 Go 后台：

| 规则 | 示例 |
|---|---|
| 单笔金额上限 | ≤ 总资产 5% |
| 单标的持仓上限 | ≤ 20% |
| 总仓位上限 / 杠杆 | ≤ 100% |
| 日内最大亏损熔断 | -3% 全平并停止 |
| 下单频率限制 | ≤ 10 笔/分钟 |
| 行情陈旧检查 | 最新 tick 超过 N 秒拒绝下单 |
| 价格偏离检查 | 偏离最新价 > 2% 拒单 |
| 白名单 | 标的 / 账户 / 策略 |

风控触发要落 `risk_events` 表并告警，**不允许策略绕过**。

### 4.6 时间与时区

- 全系统内部统一 **UTC**，只在展示层转本地时区；
- 行情时间戳保留交易所原始时间 + 接收时间两个字段；
- 服务器强制 NTP 同步，偏差 > 100ms 告警；
- 交易日历（节假日、半日市）单独一张表，回测和实盘共用。

### 4.7 安全

- 券商/交易所 API Key 用 **AES-GCM 或 age 加密后入库**，主密钥放环境变量 / Vault，绝不明文；
- 交易接口与查询接口权限分离，下单需二次确认（大额可设双人复核）；
- 所有写操作进 `audit_logs`（谁、何时、改了什么、IP）；
- Web 后台默认不暴露公网，走 VPN / 内网 + 反向代理 + 基础认证。

### 4.8 对账

每日收盘后自动跑：
- 本地持仓 vs 交易所持仓
- 本地成交 vs 交易所成交
- 本地现金 vs 交易所余额

任一不一致 → 告警 + 自动停止该账户交易。这是唯一能兜住“代码 bug 导致乱下单”的机制。

---

## 5. 数据模型（MySQL 核心表）

```
users(id, username, pwd_hash, role, created_at)
accounts(id, broker, account_no, env[papper/live], credentials_enc, status)
strategies(id, name, code_ref, market, freq, owner_id, status)
strategy_instances(id, strategy_id, account_id, params_json, status, started_at)
runs(id, instance_id, pid, host, started_at, stopped_at, exit_reason)   -- 运行实例
signals(id, strategy_id, symbol, side, qty, price, ts, payload_json)
orders(id, client_order_id UNIQUE, broker_order_id, account_id, strategy_instance_id,
       symbol, side, type, price, qty, filled_qty, avg_price, status,
       reject_reason, created_at, updated_at)
trades(id, order_id, broker_trade_id UNIQUE, price, qty, fee, ts)
positions(account_id, symbol, qty, avail_qty, avg_cost, updated_at)  -- 唯一索引(account_id,symbol)
position_snapshots(account_id, symbol, qty, price, pnl, snap_date)   -- 每日快照
risk_rules(id, scope, type, params_json, enabled)
risk_events(id, rule_id, order_id, action, detail, created_at)
backtests(id, strategy_id, params_json, date_from, date_to, status, metrics_json)
bars_1m / bars_1d  -- 若不用 ClickHouse 才放这里，按 trade_date 分区
audit_logs(id, user_id, action, target, before_json, after_json, ip, created_at)
alerts(id, level, source, message, acked, created_at)
jobs(id, type, payload, status, retry, run_at)   -- 定时/异步任务
```

索引要点：`orders(status, created_at)`、`orders(account_id, symbol)`、`trades(order_id)`、`positions` 复合唯一。

Redis key 规划：

```
cache:quote:{symbol}          # 最新行情，TTL 短
lock:strategy:{id}            # 分布式锁，防重复启动
stream:md.{freq}
stream:sig.{strategy_id}
stream:order.events
hb:agent:{agent_id}           # 心跳，TTL 15s
```

---

## 6. 目录结构建议

> 下面是**通用目标结构**。当前仓库已落地的部分见 [`PLAN_V1.md`](./PLAN_V1.md) §7。

```
trading/
├── docs/                     # 本计划、API 契约、schema 变更记录
├── proto/                    # 控制面 protobuf（Go + Python 共同生成）
├── deploy/
│   └── docker-compose.yml    # mysql/redis；后续再加 clickhouse/minio/grafana
├── backend/                  # Go
│   ├── cmd/api/
│   ├── internal/{api,auth,store,secretbox,quantcli}   # 已实现
│   └── internal/{strategy,order,position,risk,ws,agent,metrics}   # 后续
├── quant/                    # Python
│   ├── pyproject.toml
│   ├── quant/
│   │   ├── core/             # Context, Event, Clock, 类型定义（回测实盘共用）
│   │   ├── data/             # collectors, cleaners, storage, calendar
│   │   ├── backtest/         # engine, matching, cost, metrics
│   │   ├── trade/            # oms, brokers(ccxt/ctp/...), risk
│   │   ├── strategies/       # 每个策略独立包 + params schema
│   │   └── agent/            # gRPC client, 心跳, 任务循环
│   └── tests/
├── frontend/                 # Vue 3 管理后台（独立工程）
└── ops/                      # 回放、对账、数据修复脚本
```

---

## 7. 分阶段计划

> 以**单人全职**估算。团队 2–3 人可并行压缩约 40%。
> MVP 定义：**单市场 + 多用户独立账户 + 1~2 个策略 + 分钟级频率**。先窄后宽，别一上来做多市场多策略。

### Phase 0 — 需求与约束确认（3–5 天）

产出：一页纸 `docs/REQUIREMENTS.md`
- 交易市场与标的范围（A股 / 期货 / 加密 / 美股）——决定 API、T+1、涨跌停、保证金逻辑
- 频率（日线 / 分钟 / tick）——决定存储与延迟预算
- 资金规模与可承受回撤
- 券商/交易所 API 是否已开通、是否支持模拟盘
- 合规约束（是否代客、是否涉及资管牌照）
- 单机还是多机、预算

**验收**：能把“第一个要跑的策略”用一句话写清楚（标的、频率、信号、退出规则）。

### Phase 1 — 基础设施骨架（1–1.5 周）

- monorepo 初始化、Makefile、pre-commit、CI（lint + test）
- docker-compose：MySQL / Redis / ClickHouse / MinIO / Grafana
- 数据库迁移体系 + 第一批表
- Go API 骨架：健康检查、JWT 登录、RBAC、统一错误码、结构化日志、Prometheus metrics
- Python 骨架：uv、pydantic 配置、日志、基础 CLI
- proto 目录 + 生成脚本（Go/Python 双向 codegen）

**验收**：`make up` 一键起全栈；`/api/health` 返回服务与版本；CI 绿。

### Phase 2 — 行情数据链路（2 周）

- Collector：单市场单品种接入、断线重连、去重、断点续采
- 数据标准化：统一 symbol 命名、UTC 时间戳、字段校验
- 落盘：原始数据 → Parquet（MinIO）；分钟线 → ClickHouse
- 数据质量：缺口检测 + 自动补齐、异常值过滤、交易日历
- 复权处理（股票必需）
- 每日数据任务调度（用 Go 的 jobs 表 + worker，或 cron）

**验收**：连续采集 5 个交易日无缺口；任意历史区间可 1 分钟内导出 DataFrame；补数脚本可重放。

### Phase 3 — 回测引擎（2 周，可与 Phase 2 后半并行）

- 事件驱动回测内核（bar 级，预留 tick 扩展）
- 撮合模型：手续费/滑点/涨跌停/停牌/T+1/成交量约束
- 组合与资金账户（多标的同时持仓）
- 绩效指标：年化、夏普、Sortino、最大回撤、Calmar、胜率、盈亏比、换手率、容量估算
- 报告输出：净值曲线、回撤曲线、月度收益热力图、交易明细
- **防未来函数检查**：数据访问层强制 `as_of` 时间

**验收**：同一策略在回测引擎与外部参考实现（如 vectorbt）上，同一区间收益差异 < 5%（差异需能解释）。

### Phase 4 — 交易执行与风控（2.5–3 周）

- OMS：订单状态机、幂等、挂单恢复、部分成交处理
- Broker 适配器接口 + 第一个实现（优先选有模拟盘的）
- Pre-trade 风控库 + 规则配置
- Agent：gRPC 注册/心跳/指令执行/优雅退出
- 信号 → 订单 → 回报 全链路打通，写 MySQL + `order.events`
- Watchdog：心跳丢失、行情断流、持仓漂移 → 熔断

**验收**：模拟盘连续跑 3 个交易日，订单状态与券商完全一致，无重复单、无丢单；拔网线/杀进程后可自动恢复。

### Phase 5 — Web 后台（2 周，与 Phase 3/4 并行）

页面优先级：
1. 登录 / 用户与权限
2. **监控大屏**：账户权益、当日盈亏、持仓、运行中的策略、最近订单、告警
3. 策略实例管理：启停、参数编辑（按 params schema 自动生成表单）、日志查看
4. 订单 / 成交 / 持仓查询与导出
5. 回测：提交任务、进度、报告对比（多组参数并列）
6. 风控规则配置、审计日志、告警中心

技术点：WebSocket 推送 + 断线重连 + 增量更新；图表用 lightweight-charts。

**验收**：从后台点“启动策略”到看到第一笔订单，全流程无需登录服务器。

### Phase 6 — Paper Trading 验证（2 周，不可跳过）

- 至少 2 周模拟盘，覆盖：正常交易日、跳空、涨跌停、半日市、断网
- 回测 vs 模拟盘的滑点/成交率对比，校准成本模型
- 故障演练：杀策略进程、杀 MySQL、Redis 重启、时钟漂移
- 对账脚本上线

**验收**：连续 10 个交易日无人工干预、无告警未处理、对账零差异。

### Phase 7 — 小额实盘与运维（持续）

- 单策略、最小资金量实盘，风控阈值收紧
- 每日复盘：信号 vs 成交偏离、滑点统计
- 逐步加策略、加资金、加市场
- 补齐：备份恢复演练、密钥轮换、容量监控

**验收**：实盘 1 个月，实际滑点与模型偏差 < 30%，最大回撤在预期内。

### 时间线总览

```
周次   1   2   3   4   5   6   7   8   9  10  11  12  13  14
P0    ██
P1      ████
P2          ████████
P3              ████████
P4                  ████████████
P5            ████████
P6                          ████████
P7                                  ██████→
```

**MVP（可模拟盘）约 10–11 周；到可小额实盘约 14 周。**

---

## 8. 风险清单

| 风险 | 影响 | 对策 |
|---|---|---|
| 回测过拟合 | 实盘必亏 | 样本外验证、参数敏感性分析、限制参数个数、Walk-forward |
| 未来函数 / 数据泄漏 | 回测虚高 | 数据层强制 as_of、复权用当时可得数据、财报按披露日 |
| 订单状态不一致 | 重复下单 / 裸持仓 | 状态机 + 幂等 key + 启动恢复 + 每日对账 |
| 行情断流仍交易 | 用旧价成交 | 陈旧行情检查 + Watchdog 熔断 |
| API Key 泄露 | 资金损失 | 加密存储、最小权限（禁提现）、IP 白名单 |
| 单点故障 | 策略停摆 | 进程守护 + 心跳 + 自动重启 + 告警 |
| MySQL 被行情压垮 | 全站不可用 | 行情与业务库物理隔离（不同实例/不同库） |
| 时钟漂移 | 撮合与回测错位 | NTP + 偏差告警 + 双时间戳 |
| 过度设计 | 3 个月写不出第一笔单 | 严格按 Phase 走，Phase 4 之前不做多市场/多策略 |

---

## 9. 现在需要你确认的 5 件事

这些直接决定选型和工期，建议在 Phase 0 就定下来：

1. **交易市场**：A股 / 期货 / 加密货币 / 美股？（决定 API、T+1、涨跌停、保证金）
2. **交易频率**：日线 / 分钟 / tick？（决定要不要 ClickHouse、要不要做低延迟）
3. **券商/交易所接口**：是否已开通？有没有模拟盘？
4. **使用人数**：只有你自己，还是要给别人用（涉及多租户、权限、合规）？
5. **投入方式**：单人业余 / 单人全职 / 小团队？（工期差异 2–3 倍）

---

## 10. 建议的第一步

不要先写 Web 页面。按这个顺序动手，最快拿到正反馈：

1. `docker-compose` 起 MySQL + Redis
2. 定义 `orders` / `trades` / `positions` 三张表 + 订单状态机
3. 写一个假的 Broker（内存撮合），跑通 `信号 → 订单 → 成交 → 持仓更新`
4. 再写真实 Broker 适配器和策略

**先把"钱怎么流动"跑通，再谈界面和数据。**
