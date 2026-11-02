# Trading

加密货币量化交易系统。目标：Binance 现货、1 分钟级、多用户、单人维护。

- 计划与架构：[`docs/PLAN_V1.md`](docs/PLAN_V1.md)（可执行版）、[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md)（通用架构）
- 当前阶段：**数据链路 + 策略框架 + 回测引擎 + 多用户管理后台**

## 当前进度

| 模块 | 状态 |
|---|---|
| 行情回填 / 实时采集 / Parquet 存储 / 质量检查 | 可用 |
| 策略注册表 + 内置策略（双均线、唐奇安） | 可用 |
| 事件驱动回测 + 手续费/滑点/参与率 + 绩效报告 | 可用 |
| Go Gin API（登录、用户、策略、回测、凭据） | 可用 |
| Vue 3 管理后台（登录、回测、账户设置、用户管理） | 可用 |
| 多用户隔离（JWT + `user_id` + 独立报告目录） | 可用 |
| Binance API Key 加密存储（AES-256-GCM） | 可用 |
| 实盘下单 / 仓位管理 / gRPC 控制面 | 未开始 |

## 目录

```
backend/    Go Gin API（只提供 JSON，不托管前端）
frontend/   Vue 3 + Vite + Element Plus + ECharts 管理后台
quant/      Python：数据采集、存储、策略、回测
deploy/     systemd 服务模板
data/       行情数据（Parquet，不入 git）
docs/       计划与架构
```

**前后端完全分离**：`frontend` 是独立工程，开发时 Vite 代理 `/api` 到 Go，生产时由 nginx 托管静态文件并反向代理 `/api`。Go 二进制里没有 HTML。

## 快速开始

前置：Python 3.13、Go 1.26+、Node 20+、Docker。

```bash
# 1. 基础设施（MySQL + Redis）
cp .env.example .env
make secrets       # 生成 AUTH_SECRET / CREDENTIALS_KEY 并写入 .env
make up

# 2. Python 环境
make install

# 3. 拉 2 天 BTCUSDT 1 分钟线
make fetch

# 4. 启动 Go API（:8080）
make api

# 5. 另开终端启动前端（:5173）
make web-install   # 首次
make web-dev
```

打开 <http://localhost:5173>。首次启动会进入 **创建管理员** 页面：第一个账号自动成为管理员，
之后由管理员在“用户管理”里创建其他用户。登录后：选择策略 → 改参数 → 运行回测，
右侧显示绩效、权益/回撤曲线和成交记录。策略库页面会列出所有已注册策略及其参数范围。

> 本地开发如果不想生成密钥：`AUTH_SECRET` 为空时后端会随机生成（重启后所有会话失效），
> `CREDENTIALS_KEY` 为空时“账户设置”里的 API Key 功能会返回 503。

## 架构边界

```
Vue 后台 (:5173)  --HTTP/JSON + Cookie-->  Go Gin API (:8080)  --子进程-->  Python quant CLI
                                                │
                                                └── MySQL（用户 / API Key / 回测历史）
                                                └── Redis（后续业务缓存与消息）
```

- 前端**不在交易链路上**，只调用 API；后台挂了不影响策略进程。
- Go 只做业务 API。策略发现、参数校验、回测都在 Python，避免两套规则。
- 当前 Go → Python 用 `python -m quant.cli ... --json` 子进程调用，参数用 argv 传递，不过 shell。
  后续替换成 gRPC 时，HTTP 契约保持不变。
- CORS 由 `CORS_ORIGINS` 控制，默认只允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`。
- 登录态是 HttpOnly Cookie（`trading_session`，默认 7 天）。开发时走 Vite 代理，生产走 nginx 同源反代，
  因此 Cookie 不需要跨站。

### 多用户模型

- **第一个注册的账号是管理员**，之后只能由管理员创建用户。
- 每个用户拥有独立的 Binance API Key（加密存储）、回测历史、报告目录
  `data/reports/user_<id>/...`。
- 行情采集是**全局共享**的，不按用户重复采集；“不同用户不同交易对”是用户配置，不是数据复制。
- 回测的“单飞”限制按用户计算：一个用户同一时间只能跑一个回测，不同用户可以并行。
- 所有业务查询都带 `user_id`，从 JWT 取，**不信任请求体里的用户标识**。
- 管理员目前只能看自己的回测历史；用户列表和账号管理在管理员侧。跨用户审计后续再加。

### 策略是怎么“切换”的

策略是**仓库内的代码插件**，后台不能上传或热替换代码。后台能做的是：

1. 从注册表读取策略列表和 JSON Schema；
2. 自动生成参数表单；
3. 用选定参数跑回测 / 启动新实例。

实盘切换的语义是：**停止旧实例 → 平仓或接管仓位 → 用新策略启动**，不做运行时热替换。实盘部分尚未实现。

新增策略：在 `quant/quant/strategies/` 下新建模块并 `@register`，重启 API 后自动出现在下拉框和策略库。

## HTTP API

除 `/api/health` 和登录相关接口外，都需要登录 Cookie（或 `Authorization: Bearer <token>`）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查与版本（公开） |
| GET | `/api/auth/status` | `needs_setup`，前端据此显示首次创建管理员（公开） |
| POST | `/api/auth/bootstrap` | 仅在系统无用户时创建第一个管理员（公开） |
| POST | `/api/auth/login` | 邮箱密码登录，写入 HttpOnly Cookie（公开） |
| POST | `/api/auth/logout` | 清除会话（公开） |
| GET | `/api/auth/me` | 当前用户 |
| GET | `/api/strategies` | 策略列表、`params_schema`、默认值 |
| POST | `/api/backtests` | 同步执行回测，返回绩效与曲线 |
| GET | `/api/backtests?limit=20` | 当前用户最近的回测 |
| GET | `/api/backtests/:id` | 当前用户的单次回测完整结果 |
| GET | `/api/me/credentials` | 当前用户的 Binance Key 状态（只返回掩码） |
| PUT | `/api/me/credentials` | 加密保存/覆盖 Binance Key |
| DELETE | `/api/me/credentials` | 删除当前用户的 Binance Key |
| GET | `/api/users` | 用户列表（仅管理员） |
| POST | `/api/users` | 创建用户（仅管理员） |

回测请求示例：

```json
{
  "strategy": "ma_cross",
  "symbols": ["BTCUSDT"],
  "days": 30,
  "interval": "1m",
  "initial_cash": 10000,
  "fee_rate": 0.0005,
  "slippage_bps": 2,
  "params": { "fast": 10, "slow": 30, "atr_window": 14, "atr_mult": 3, "target": 0.95 }
}
```

响应包含 `metrics`、`monthly_returns`、`equity_curve`、`drawdown_curve`、最近 500 笔成交、`report_dir`。
样本不足时 `cagr` / `sharpe` / `sortino` / `volatility` / `calmar` 返回 `null`（界面显示 `n/a`），不伪装成 0。

## 回测与策略 CLI

```bash
cd quant

# 列出策略及参数
.venv/bin/python -m quant.cli strategies
.venv/bin/python -m quant.cli strategies --json   # 后台用的契约

# 回测（默认 30 天、1 分钟、BTCUSDT）
.venv/bin/python -m quant.cli backtest -s BTCUSDT -s ETHUSDT -d 30

# 指定策略与参数
.venv/bin/python -m quant.cli backtest \
  --strategy ma_cross -s BTCUSDT -d 7 \
  -p fast=10 -p slow=30 -p atr_mult=2.5

# 机器可读输出（与 HTTP API 同一份 JSON）
.venv/bin/python -m quant.cli backtest -s BTCUSDT -d 7 --json
```

报告默认写入 `data/reports/<strategy>_<symbols>/<timestamp>/`：`metrics.json`、`equity.svg`、`drawdown.svg`。
通过 Go API 触发时按用户分区：`data/reports/user_<id>/<strategy>_<symbols>/<timestamp>/`。

回测时序（防止未来函数）：

```
bar[i] 收盘 → 策略只能看到 bars[0..i] → 下单
bar[i+1] 开盘 → 按开盘价 + 滑点成交
```

买入受单根 K 线成交量 1% 限制；**卖出不受限**，避免“因为那根 K 线太薄而卖不掉”的假结果。

## 前端构建与部署

```bash
cd frontend
npm run build      # 产物在 frontend/dist
```

生产用 nginx 托管 `dist`，并把 `/api` 反代到 Go。**推荐同域部署**，这样登录 Cookie 天然生效：

```nginx
server {
    listen 443 ssl http2;
    server_name trading.example.com;

    root /srv/trading/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

上线时把 `SESSION_COOKIE_SECURE=true`，并确保 `AUTH_SECRET` / `CREDENTIALS_KEY` 已写入后端环境
（`deploy/systemd/trading-api.service` 使用 `EnvironmentFile=/srv/trading/.env`）。如果前端和 API 不同域，建议保持同一主域名下的子域，
并在后端 `CORS_ORIGINS` 里加入前端完整 Origin；完全不同的站点需要改用 Bearer Token，当前默认的
`SameSite=Lax` Cookie 不适合。

后端环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` | `127.0.0.1` | 监听地址；对外暴露时改为 `0.0.0.0` |
| `PORT` | `8080` | API 端口 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔 |
| `AUTH_SECRET` | 空 | 会话签名密钥；空则启动时随机生成，重启后会话失效 |
| `CREDENTIALS_KEY` | 空 | 32 字节 base64，加密 Binance Key；空则凭据接口返回 503 |
| `SESSION_COOKIE_SECURE` | `false` | HTTPS 部署时设为 `true` |
| `MYSQL_DSN` | 空 | 完整 DSN；设置后忽略下面的分项 |
| `MYSQL_HOST` | `127.0.0.1` | MySQL 地址 |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_USER` | `trader` | MySQL 用户 |
| `MYSQL_PASSWORD` | `trader` | MySQL 密码 |
| `MYSQL_DATABASE` | `trading` | 数据库名 |
| `QUANT_PYTHON` | `quant/.venv/bin/python` | Python 解释器 |
| `QUANT_ROOT` | 自动向上查找 | 仓库根目录 |

> `AUTH_SECRET` 与 `CREDENTIALS_KEY` 用 `make secrets` 生成。修改 `CREDENTIALS_KEY` 会导致已保存的
> API Key 无法解密，需要让用户重新录入。

## 常用命令

```bash
make secrets       # 生成 AUTH_SECRET / CREDENTIALS_KEY 写入 .env
make test          # Python 测试
make lint          # ruff
make fmt           # 自动格式化
make test-api      # Go vet + test
make test-web      # Vue 类型检查
make web-build     # 前端生产构建
make check         # Python + Go + Vue 全量检查
make api           # 启动 Go API
make web-dev       # 启动前端开发服务器
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
data/reports/user_<id>/<strategy>_<symbols>/<timestamp>/
```

写入是**幂等**的：重复拉取同一区间不会产生重复行，重叠部分以最新数据为准（便于修复错误的 bar）。
每个 symbol 用文件锁串行化写入，写盘是先写临时文件再 `rename`，进程崩溃不会损坏已有月份。

## 设计约束（务必遵守）

- 全系统时间统一 **UTC**，只在展示层转换。
- 只落**已收盘**的 K 线（`close_time < now`），避免回测看到未完成的 bar。
- 下单前必须用 `tickSize` / `stepSize` / `minNotional` 量化，见 `quant/core/rounding.py`。
- 行情数据不进 MySQL，业务数据（用户/API Key/订单/持仓/审计）才进 MySQL。
- Web 后台不在交易链路上，后台挂了策略要能继续跑。
- 每个用户的数据必须带 `user_id`，从会话解析，禁止信任请求体里的用户标识。
- Binance API Key 只存密文，接口只返回掩码；禁止把 Secret 写日志或返回前端。
- 策略代码是全局插件；用户能选择策略、交易对和参数，但不能上传或热替换代码。
