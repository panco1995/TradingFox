# 量化交易系统 · V1 执行计划

> 基线：**加密货币 · 分钟级 · 单人业余（约 10h/周）**
> 版本 v1.0 · 2026-10-31
> 配套阅读：`docs/PROJECT_PLAN.md`（通用架构与设计原则）

---

## 0. 相对通用架构的 3 个简化

业余项目的最大风险不是技术难度，而是**运维负担耗光时间**。所以：

| 原方案 | V1 改为 | 原因 |
|---|---|---|
| ClickHouse | **Parquet + DuckDB** | 分钟级数据量（哪怕 500 个币种也就 ~70 万行/天）用不上 ClickHouse；DuckDB 直接查 Parquet 做研究，零运维 |
| MinIO / 对象存储 | **本地磁盘 + rclone 定时备份** | 单机自用，没必要引入对象存储 |
| 自研完整监控大屏 | **Grafana 负责监控，自研 Web 只做"配置 + 查询 + 回测"** | Grafana 免费且开箱即用，省下至少 1 周 |

保留不变的部分：Go 做业务 API、Python 做采集/策略/交易、MySQL 存业务事实、Redis 做缓存与消息流、OMS 唯一事实源、独立风控、每日对账。

**架构最终形态：**

```
        浏览器
          │
   ┌──────▼──────┐        ┌──────────┐
   │  Go Web API │◄───────┤ Grafana  │  (Prometheus 数据源)
   └──┬───────┬──┘        └──────────┘
      │       │ gRPC(控制面)
   ┌──▼──┐  ┌─▼──────────────────────────────┐
   │MySQL│  │  Python 进程集群（同一台 VPS）   │
   └─────┘  │  collector / strategy / oms    │
   ┌─────┐  │  watchdog / recon              │
   │Redis│◄─┤  (Redis Stream 作数据面)        │
   └─────┘  └───────────┬────────────────────┘
                        │ WSS / REST
                   ┌────▼─────┐
                   │ Binance  │  testnet → 实盘
                   └──────────┘
```

部署：**1 台海外 VPS（2C4G，东京/新加坡）**，docker-compose 全栈。成本约 $10–20/月。

---

## 1. MVP 范围（写死，防止范围失控）

### ✅ 要做

- 交易所：**Binance 现货**（只做现货，不碰合约）
- 标的：**BTC/USDT、ETH/USDT** 两个（够验证多标的逻辑，又不至于分散精力）
- 频率：**1 分钟 K 线**
- 策略：**1 个**（建议双均线 + ATR 止损，规则简单、可解释）
- 环境：**先 testnet，跑通后才小额实盘**
- Web：登录 / 首次创建管理员、策略回测、策略库、账户设置（Binance Key）、用户管理（管理员）——已可用；
  后续再加策略实例启停、订单/持仓/成交查询、告警列表
- 监控：Grafana + Prometheus 基础面板

### ❌ 明确不做（V2 再说）

- 合约 / 杠杆 / 资金费率
- 多交易所
- tick / 盘口 / 高频
- 机器学习、因子库、组合优化
- 复杂 RBAC / 组织 / 计费（V1 只做 `admin` / `user` 两种角色 + 每个用户独立 Binance Key）
- 移动端
- 自动参数寻优平台（先手工跑几组）

---

## 2. 加密货币特有的设计要点

这部分是通用计划里没有、但 crypto 一定会踩的坑。

### 2.1 精度与最小下单量（最高频的报错来源）

下单前必须用 `exchangeInfo` 里的 filter 做量化：

| Filter | 作用 |
|---|---|
| `PRICE_FILTER.tickSize` | 价格精度 |
| `LOT_SIZE.stepSize` | 数量精度 & minQty |
| `NOTIONAL` / `MIN_NOTIONAL` | 最小名义金额（通常是 5–10 USDT） |

规则：
- 启动时拉 `exchangeInfo` 落库到 `symbols` 表，**定期刷新**（交易所会改）；
- 数量向下取整到 `stepSize`，价格按方向取整到 `tickSize`；
- 量化后 `price * qty` 低于 `minNotional` 直接放弃这单并记日志，**不要发出去让交易所拒绝**。

### 2.2 幂等与 clientOrderId

- 自定义 `clientOrderId`，格式 `qt{strategyId}{yyMMddHHmmss}{seq}`，限制长度与字符集（Binance 要求 `^[\.A-Z\:/a-z0-9_-]{1,36}$`）；
- 超时重试时用**同一个** clientOrderId，交易所会返回重复单错误，据此判断是否已下单成功；
- 重启后用它反查交易所，恢复本地状态。

### 2.3 时钟偏差

签名请求带 `timestamp` 和 `recvWindow`，本机时间偏差超过窗口会直接 `-1021` 报错。
- 服务器开 NTP，容器内也校时；
- 启动时对比 `/api/v3/time`，偏差 > 1s 告警并拒绝交易。

### 2.4 限频

- 交易所权重是按 IP 算的，**所有请求走同一个限流器**（令牌桶），不要各模块各自发；
- 权重值从 `exchangeInfo.rateLimits` 读，不要硬编码（会变）；
- 退避策略：429 → 读 `Retry-After`；418 → 说明已被封，立刻停手。

### 2.5 成交与滑点

- 下单用 `newOrderRespType=FULL`，直接拿到成交明细；
- 记录 **决策价 → 发送价 → 成交价** 三者的差，这是后续调参最重要的数据；
- 限价单优先（maker 费率约 taker 的 1/2.5），但要有超时转市价/撤单逻辑。

### 2.6 无交易日历，但有"日界"

- 24/7 交易，没有停牌和涨跌停，回测不需要交易日历；
- 但**自然日/UTC 日界**仍然存在（统计、日亏损熔断、资金费结算都用 UTC 00:00），统一用 UTC。

### 2.7 断线与熔断

- WebSocket 断线 → 自动重连 + 用 REST 补齐缺口；
- 断线超过 30s → **停止开新仓**（可以不管存量仓位）；
- 心跳：Binance 每 3 分钟发 ping，超过 10 分钟无消息视为假连接，主动重连。

### 2.8 安全

- API Key 只开 **现货交易** 权限，**关闭提现**，绑定 VPS IP 白名单；
- Key 用 AES-GCM 加密入库，主密钥走环境变量；
- 实盘账户只放**可完全损失**的金额，起步建议 500–1000 USDT；
- 定期轮换 Key。

---

## 3. 数据方案（简化版）

### 目录布局

```
/data
├── raw/klines/exchange=BINANCE/type=spot/symbol=BTCUSDT/1m/2026-10.parquet
├── raw/trades/exchange=BINANCE/symbol=BTCUSDT/2026-10-31.parquet   # 可选，后期加
└── meta/symbols.parquet
```

### 采集策略

1. **历史回填**：REST `GET /api/v3/klines`，每次 1000 根，按时间游标翻页，写入当月 Parquet；
2. **实时增量**：WS `kline_1m` 流，按 `x`（isFinal）字段判断是否为已收盘的 bar，**只有 isFinal=true 才落盘**；
3. **断点续采**：记录每个 symbol 的最后同步时间，启动时自动补齐；
4. **校验**：每日检查 bar 连续性（DTO 序列是否缺根）、重复（open_time 唯一）、异常（high<low 等），生成质量报告。

### 为什么用 Parquet 而不是 MySQL

- 研究侧用 DuckDB 一句 SQL 就能查任意区间：
  ```sql
  SELECT * FROM read_parquet('/data/raw/klines/**/*.parquet')
  WHERE symbol='BTCUSDT' AND open_time >= '2025-01-01'
  ```
- 压缩率高（1m bar 约 50–100 字节/根），一年两币种不到 200MB；
- MySQL 只存业务表，查询永远快。

---

## 4. 回测的关键校准（crypto 版）

| 项 | 值 |
|---|---|
| Taker 手续费 | 0.05%（保守取，有 BNB 折扣可下调） |
| Maker 手续费 | 0.02% |
| 滑点 | 1m 级别建议 1–3 bps，或用"决策用 close、成交用下一根 open"代替 |
| 成交时点 | `on_bar(bar[i])` 决策 → `bar[i+1].open` 成交（**这是防未来函数的核心**） |
| 成交约束 | 单笔不超过该 bar 成交量的 1%，否则按比例成交 |
| 最小下单 | 遵守 `minNotional`，否则回测会成交实盘下不出的单 |

**必做验证**：同一策略回测 vs 测试网实盘跑 2 周，对比成交价偏离与成交率。偏差超过 30% 说明成本模型错了，回测收益不可信。

---

## 5. 数据模型调整

在通用表结构基础上，crypto 需要补充：

```sql
-- 交易标的元数据（从 exchangeInfo 同步）
symbols(id, exchange, symbol, base_asset, quote_asset,
        tick_size, step_size, min_qty, min_notional, status, updated_at)

-- orders 增加字段
orders (
  ...,
  exchange, symbol,
  client_order_id   VARCHAR(36) UNIQUE,
  exchange_order_id VARCHAR(64),
  type              ENUM('LIMIT','MARKET'),
  time_in_force     ENUM('GTC','IOC','FOK'),
  fee, fee_asset,
  decision_price    DECIMAL(20,8),   -- 策略决策时看到的价格
  submit_price      DECIMAL(20,8)    -- 实际发单价
)

-- 决策链路追踪（调参的核心数据）
decisions(id, strategy_id, symbol, bar_open_time, signal, target_qty,
          decision_price, ts)
```

`positions` 按 `(account_id, symbol)` 唯一，`avail_qty` 在现货 T+0 下等于 `qty`（保留字段为将来合约准备）。

---

## 6. 周计划（20 周 × 10h）

原则：**每个任务控制在 2–4 小时可完成**，避免"只能周末做的大任务"，否则一断档就停摆。

### 阶段一：跑通数据（W1–W4）

| 周 | 任务 | 产出 / 验收 |
|---|---|---|
| W1 | 开交易所测试网账号、建 VPS、docker-compose（MySQL+Redis）、仓库骨架、Go 与 Python 各自 hello world | `make up` 起全栈；两边都能读到 Redis |
| W1 | 拉 `exchangeInfo` 写进 `symbols` 表 | 能正确显示 BTCUSDT 的 tickSize/stepSize |
| W2 | REST 历史 K 线回填脚本（单 symbol） | 能回填 2 年 1m 数据到 Parquet |
| W2 | WS 实时 1m 采集（单 symbol，isFinal 落盘） | 连续跑 24h 无重复、无缺口 |
| W3 | 扩到 2 个 symbol + 断点续采 + 每日质量校验 | 断网重启后能自动补齐 |
| W4 | DuckDB 查询封装 + 数据可视化抽查 | 一条 SQL 取出任意区间 DataFrame；肉眼比对交易所图表无误 |

**里程碑 M1**：稳定采集 7 天，数据零缺口。

### 阶段二：回测与策略（W5–W8）

| 周 | 任务 | 产出 / 验收 |
|---|---|---|
| W5 | 回测内核：事件循环、Context、Broker 模拟、费率/滑点 | 能跑通一个 buy-and-hold |
| W6 | 绩效指标 + 报告图表 + 未来函数检查（`as_of` 强制） | 输出净值/回撤/月度热力图 |
| W7 | 写第一个策略（双均线 + ATR 止损），参数化 | 回测 2 年数据出报告 |
| W8 | 参数敏感性分析（手工跑 20 组）+ 样本外验证 | 结论写进 `docs/strategy_v1.md`，明确"是否有 edge" |

**里程碑 M2**：有一个能在样本外不崩的策略，且知道它的成本敏感度。

> ⚠️ 如果 W8 结束时策略没有正期望，**不要继续开发交易链路**，先回去改策略。这是业余项目最容易走的弯路：系统写得漂亮，策略是负期望。

### 阶段三：交易执行（W9–W13）

| 周 | 任务 | 产出 / 验收 |
|---|---|---|
| W9 | OMS 骨架：状态机、幂等、落库 | 单测覆盖状态迁移，禁止非法迁移 |
| W9 | Binance Broker 适配器（testnet）：下单/撤单/查单/查余额 | 能手工下一笔限价单并正确回报 |
| W10 | Agent + gRPC 控制面：注册、心跳、启停、参数下发 | 后台点按钮能启动/停止策略 |
| W11 | 独立风控库 + 规则配置 | 触发限额能拒单并落 `risk_events` |
| W12 | Watchdog：心跳、行情断流、时钟偏差、持仓漂移 | 拔网线后 30s 内停止开仓并告警 |
| W13 | 全链路联调：信号→订单→成交→持仓→推送 | 测试网跑通 3 天 |

**里程碑 M3**：测试网无人值守跑 3 天，订单与交易所完全一致。

### 阶段四：Web 与监控（W14–W16）

| 周 | 任务 | 产出 |
|---|---|---|
| W14 | Go API：JWT 登录、用户/角色、策略 CRUD、启停、订单/持仓查询 | Postman 全通 |
| W14 | Prometheus metrics + Grafana 看板（权益、订单数、延迟、错误率） | 一张能看懂的监控图 |
| W15 | 前端 5 个页面：登录 / 回测 / 策略库 / 账户设置 / 用户管理 | 能用，不求好看 |
| W16 | WebSocket 实时推送 + 告警中心 | 订单变化 2s 内出现在页面上 |

**里程碑 M4**：从浏览器完成"改参数 → 重启策略 → 看到订单"，全程不登服务器。

### 阶段五：测试网长跑（W17–W18）

| 周 | 任务 |
|---|---|
| W17 | 连续跑 7 天，记录所有异常；回测 vs 实盘成交价对比 |
| W18 | 故障演练：杀进程、重启 Redis、改系统时间、限频打满；修 bug |

**里程碑 M5**：连续 10 天无人工干预、对账零差异、滑点偏差 < 30%。

### 阶段六：小额实盘（W19–W20+）

| 周 | 任务 |
|---|---|
| W19 | 实盘账户、500–1000 USDT、风控阈值收紧到 1/3；先只跑 1 个 symbol |
| W20 | 每日复盘：决策价/成交价/滑点；跑满 4 周再考虑加资金 |

---

## 7. 目录结构（最终版）

```
trading/
├── docs/
│   ├── PROJECT_PLAN.md          # 通用架构
│   ├── PLAN_V1.md               # 本文件
│   ├── strategy_v1.md           # 策略说明与回测结论
│   └── decisions/               # ADR：每做一个技术决定记一条
├── proto/                       # agent.proto
├── deploy/
│   ├── systemd/                  # trading-api / quant-collector / quant-quality
│   └── mysql/init/               # 初始化 SQL（可选）
├── docker-compose.yml            # MySQL + Redis
├── backend/                     # Go
│   ├── cmd/api/main.go
│   └── internal/
│       ├── api/                 # Gin 路由、CORS、回测/用户/凭据 handler
│       ├── auth/                # bcrypt、JWT、Cookie 中间件
│       ├── store/               # MySQL 访问与自动建表
│       ├── secretbox/           # AES-256-GCM 加密 API Key
│       ├── quantcli/            # 调用 Python CLI
│       └── {strategy,order,position,risk,ws,agent,metrics}/   # 后续
├── quant/                       # Python
│   ├── quant/
│   │   ├── core/                # Event, Context, Clock, Symbol, 枚举
│   │   ├── data/                # binance_rest, binance_ws, parquet_store, quality
│   │   ├── backtest/            # engine, matching, costs, metrics
│   │   ├── trade/               # oms, broker_binance, risk, reconciler
│   │   ├── strategies/ma_cross/
│   │   └── agent/               # grpc client, heartbeat, runner
│   └── tests/
├── frontend/                    # Vue 3 管理后台（独立工程）
│   └── src/
│       ├── api.ts               # fetch 封装 + 401 处理
│       ├── stores/auth.ts       # Pinia 登录态
│       ├── router/index.ts      # 登录页、路由守卫、角色限制
│       ├── layout/AdminLayout.vue
│       └── views/               # Login / Backtest / Strategies / Account / Users
├── ops/                         # 回填、校验、对账脚本
└── data/                        # 挂载卷（不进 git）
```

---

## 8. 技术栈最终确定

| 项 | 选择 | 理由 |
|---|---|---|
| 交易所 | Binance 现货（testnet 优先） | 流动性最好、文档全、测试网完善 |
| Python | 3.13 + venv + pydantic v2 + polars + duckdb | 快、省心 |
| 交易所对接 | `aiohttp` 原生 REST + `websockets` 原生 WS | 比 ccxt 少一层抽象，报错信息更直接；crypto 只有一家交易所时没必要用统一层 |
| Go | gin + slog + `go-sql-driver/mysql` + JWT | 类型安全、够快、依赖少 |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus + ECharts + Pinia | 页面少，组件现成，前后端分离 |
| 存储 | MySQL 8（业务）+ Parquet/DuckDB（行情） | 零运维 |
| 消息 | Redis Stream | 已有 Redis，够用 |
| 监控 | Prometheus + Grafana + Loki | 免费，省一周开发 |
| 部署 | docker-compose on VPS | 单人项目不要上 k8s |

---

## 9. 成本与风险

**成本**：VPS ~$15/月，数据免费，测试网免费，实盘起步 500–1000 USDT。

**风险与对策**：

| 风险 | 对策 |
|---|---|
| 业余时间碎片化导致半途而废 | 任务切到 2–4h 粒度；每阶段有可演示产出（M1–M5） |
| 策略无 edge，系统白写 | **W8 设硬门槛**：样本外无正期望就回头改策略 |
| 交易所 API 变更 / 精度报错 | `symbols` 表定时刷新；所有下单前统一量化 |
| 被限频封 IP | 全局令牌桶 + 读 `rateLimits` + 退避 |
| 密钥泄露 | 禁提现权限 + IP 白名单 + 加密存储 + 小额资金 |
| 回测过度乐观 | 决策用 close、成交用 next open；跑测试网做成本校准 |
| 地域/合规 | 自行确认所在地对交易与 API 访问的要求；用海外 VPS |
| 单点故障 | 进程守护 + Watchdog 熔断 + Grafana 告警 |

---

## 10. 下一步（本周就能开始）

按顺序，每个都是独立可完成的小任务：

1. 注册 Binance 测试网，拿到 testnet API Key
2. 买一台海外 VPS，装 Docker
3. 建仓库，写 `docker-compose.yml`（MySQL + Redis）
4. 写 `quant/data/binance_rest.py`，只做一件事：拉 BTCUSDT 最近 1000 根 1m K 线并打印
5. 拉通了再写落盘

**第一周的目标只有一个：把 1000 根 K 线正确地存成 Parquet，并用 DuckDB 读回来画个图。**
