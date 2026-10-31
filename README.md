# Trading

加密货币量化交易系统。目标：Binance 现货、1 分钟级、单账户、单人可维护。

- 计划与架构：[`docs/PLAN_V1.md`](docs/PLAN_V1.md)（可执行版）、[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md)（通用架构）
- 当前阶段：**W1 数据链路**（已可用）

## 目录

```
backend/    Go HTTP API（当前只有 /healthz、/version）
quant/      Python：数据采集、存储、回测、交易执行
deploy/     docker / mysql 初始化
data/       行情数据（parquet，不入 git）
proto/      Go <-> Python 控制面契约（待建）
```

## 快速开始

```bash
# 1. 基础设施（需要 Docker）
cp .env.example .env
make up

# 2. Python 环境
make install

# 3. 拉 2 天 BTCUSDT 1 分钟线
make fetch

# 4. 实时采集（Ctrl-C 停止）
make watch

# 5. 检查数据质量 + 终端图形 + SVG
make inspect

# 6. 质量报告（缺口/重复/异常）
make quality

# 7. Go API
make api          # http://localhost:8080/healthz
```

## 常用命令

```bash
cd quant

# 增量拉取（从本地最后一根开始，可反复执行）
.venv/bin/python -m quant.cli fetch -s BTCUSDT -s ETHUSDT --incremental

# 指定区间
.venv/bin/python -m quant.cli fetch -s BTCUSDT --start 2026-01-01 --end 2026-02-01

# 用 DuckDB 做研究查询
.venv/bin/python -m quant.cli query \
  "select date_trunc('hour', open_time) as h, avg(close) from bars group by 1 order by 1 limit 5"

# 查看交易规则（tickSize / stepSize / minNotional）
.venv/bin/python -m quant.cli symbols -s BTCUSDT -s ETHUSDT --save

# 测试 / lint
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

## 实时采集器

```bash
cd quant
# 常驻运行：WS 订阅 + 断线重连 + 自动补缺口 + 每 24h 质量自检
.venv/bin/python -m quant.cli watch -s BTCUSDT -s ETHUSDT

# 只跑一段时间（调试用）
.venv/bin/python -m quant.cli watch -s BTCUSDT --run-for 60
```

关键行为：

| 场景 | 处理 |
|---|---|
| 只落已收盘的 bar | 收到 `x=true` 才写入，避免回测看到未完成 bar |
| 启动/重连 | REST 从本地最后一根补到当前 |
| 连接建立瞬间有 bar 收盘（竞态） | 连上后再回溯 `--repair-window-minutes`（默认 120 分钟），覆盖这段空窗 |
| 历史尾部有洞（数据修订/丢包） | 同上，每次连接都会重取近 2 小时并覆盖写 |
| WS 静默 > 90s | 判定假连接，主动重连 |
| 断线 | 指数退避（1s → 60s，带抖动），重连后先补数据 |
| 进程退出 | SIGTERM/Ctrl-C 触发，先把缓冲区 flush 到盘再退出 |

部署到 VPS：`deploy/systemd/` 下有 collector 服务和每日质量检查的 timer 模板。

或者用 cron 代替 systemd timer：

```cron
10 0 * * * cd /srv/trading/quant && QUANT_DATA_DIR=/srv/trading/data \
  .venv/bin/python -m quant.cli quality -s BTCUSDT -s ETHUSDT -d 1
```

## 数据布局

```
data/raw/klines/exchange=BINANCE/type=spot/interval=1m/symbol=BTCUSDT/2026-10.parquet
data/meta/symbols.parquet
```

写入是**幂等**的：重复拉取同一区间不会产生重复行，重叠部分以最新数据为准（便于修复错误的 bar）。
每个 symbol 用文件锁串行化写入，写盘是先写临时文件再 `rename`，进程崩溃不会损坏已有月份。

## 设计约束（务必遵守）

- 全系统时间统一 **UTC**，只在展示层转换。
- 只落**已收盘**的 K 线（`close_time < now`），避免回测看到未完成的 bar。
- 下单前必须用 `tickSize` / `stepSize` / `minNotional` 量化，见 `quant/core/rounding.py`。
- 行情数据不进 MySQL，业务数据（订单/持仓/审计）才进 MySQL。
- Web 后台不在交易链路上，后台挂了策略要能继续跑。
