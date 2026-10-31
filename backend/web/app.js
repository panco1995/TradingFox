"use strict";

const $ = (selector) => document.querySelector(selector);

const state = {
  strategies: [],
  running: false,
  hasReport: false,
};

const METRIC_ROWS = [
  ["total_return", "总收益", "pct"],
  ["cagr", "年化收益", "pct"],
  ["max_drawdown", "最大回撤", "pct"],
  ["sharpe", "Sharpe", "ratio"],
  ["sortino", "Sortino", "ratio"],
  ["calmar", "Calmar", "ratio"],
  ["volatility", "年化波动", "pct"],
  ["win_rate", "胜率", "pct"],
  ["profit_factor", "盈亏比", "ratio"],
  ["exposure", "仓位暴露", "pct"],
  ["trades", "成交笔数", "int"],
  ["fees_paid", "手续费", "money"],
];

// ------------------------------------------------------------------ formatting

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);
}

function fmtPct(value, digits = 2) {
  return value == null ? "n/a" : `${(value * 100).toFixed(digits)}%`;
}

function fmtRatio(value) {
  return value == null ? "n/a" : value.toFixed(3);
}

function fmtMoney(value) {
  return value == null
    ? "n/a"
    : value.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function fmtInt(value) {
  return value == null ? "n/a" : String(Math.round(value));
}

function fmtQty(value) {
  return value == null ? "-" : value.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function fmtPrice(value) {
  if (value == null) return "-";
  const digits = value >= 100 ? 2 : value >= 1 ? 4 : 8;
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function fmtTime(iso) {
  return iso ? iso.slice(0, 16).replace("T", " ") : "-";
}

function valueFor(kind, value) {
  if (kind === "pct") return fmtPct(value);
  if (kind === "ratio") return fmtRatio(value);
  if (kind === "int") return fmtInt(value);
  if (kind === "money") return fmtMoney(value);
  return String(value);
}

// ------------------------------------------------------------------- bootstrap

async function boot() {
  try {
    const response = await fetch("/api/strategies");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.strategies = payload;

    const select = $("#strategy");
    select.innerHTML = "";
    for (const strategy of state.strategies) {
      const option = document.createElement("option");
      option.value = strategy.name;
      option.textContent = `${strategy.title} · ${strategy.name}`;
      select.appendChild(option);
    }
    select.addEventListener("change", () => renderParams(select.value));
    if (state.strategies.length === 0) {
      throw new Error("没有已注册的策略");
    }
    renderParams(select.value);
  } catch (error) {
    showError(`无法加载策略列表：${error.message}`);
  }
}

function currentSpec(name) {
  return state.strategies.find((item) => item.name === name);
}

function renderParams(name) {
  const spec = currentSpec(name);
  if (!spec) return;

  $("#strategy-description").textContent = spec.description || "";

  const tagBox = $("#strategy-tags");
  tagBox.innerHTML = "";
  for (const tag of spec.tags || []) {
    const span = document.createElement("span");
    span.className = "tag";
    span.textContent = tag;
    tagBox.appendChild(span);
  }

  const container = $("#params");
  container.innerHTML = "";
  const schema = spec.params_schema || {};
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  const keys = Object.keys(properties);

  if (keys.length === 0) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "该策略没有可调参数。";
    container.appendChild(hint);
    return;
  }

  for (const key of keys) {
    const property = properties[key] || {};
    const type = property.type || "string";
    const isBoolean = type === "boolean";
    const field = document.createElement("div");
    field.className = isBoolean ? "field field-check" : "field";

    const label = document.createElement("label");
    label.textContent = property.title || key;
    label.htmlFor = `param-${key}`;

    let input;
    if (isBoolean) {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(spec.defaults?.[key] ?? property.default ?? false);
      field.appendChild(input);
      field.appendChild(label);
    } else {
      input = document.createElement("input");
      input.type = type === "integer" || type === "number" ? "number" : "text";
      if (input.type === "number") {
        input.step = type === "integer" ? "1" : "any";
        if (property.minimum != null) input.min = property.minimum;
        if (property.maximum != null) input.max = property.maximum;
      }
      const initial = spec.defaults?.[key] ?? property.default ?? "";
      input.value = initial;
      field.appendChild(label);
      field.appendChild(input);
    }

    input.id = `param-${key}`;
    input.name = key;
    input.dataset.key = key;
    input.dataset.type = type;
    input.dataset.required = required.has(key) ? "true" : "false";
    if (property.minimum != null) input.dataset.min = property.minimum;
    if (property.maximum != null) input.dataset.max = property.maximum;
    if (property.description) input.title = property.description;
    container.appendChild(field);
  }
}

// ------------------------------------------------------------------- submission

function collectParams() {
  const params = {};
  const inputs = document.querySelectorAll("#params [data-key]");

  for (const input of inputs) {
    const key = input.dataset.key;
    const type = input.dataset.type;

    if (type === "boolean") {
      params[key] = input.checked;
      continue;
    }

    const raw = input.value.trim();
    if (raw === "") {
      if (input.dataset.required === "true") {
        throw new Error(`参数「${key}」不能为空`);
      }
      continue;
    }

    const value = Number(raw);
    if (!Number.isFinite(value)) {
      throw new Error(`参数「${key}」必须是数字`);
    }
    if (type === "integer" && !Number.isInteger(value)) {
      throw new Error(`参数「${key}」必须是整数`);
    }
    if (input.dataset.min !== undefined && value < Number(input.dataset.min)) {
      throw new Error(`参数「${key}」不能小于 ${input.dataset.min}`);
    }
    if (input.dataset.max !== undefined && value > Number(input.dataset.max)) {
      throw new Error(`参数「${key}」不能大于 ${input.dataset.max}`);
    }
    params[key] = value;
  }

  return params;
}

async function submit(event) {
  event.preventDefault();
  if (state.running) return;

  let params;
  try {
    params = collectParams();
  } catch (error) {
    showError(error.message);
    return;
  }

  const symbols = $("#symbols")
    .value.split(/[\s,]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);

  if (symbols.length === 0) {
    showError("至少需要一个标的，例如 BTCUSDT");
    return;
  }

  const body = {
    strategy: $("#strategy").value,
    symbols,
    days: Number($("#days").value) || 30,
    interval: $("#interval").value,
    initial_cash: Number($("#cash").value) || 10000,
    fee_rate: (Number($("#fee").value) || 0) / 10000,
    slippage_bps: Number($("#slippage").value) || 0,
    params,
  };

  setRunning(true);
  clearBanner();

  try {
    const response = await fetch("/api/backtests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `回测请求失败（HTTP ${response.status}）`);
    }
    renderReport(payload);
  } catch (error) {
    showError(error.message);
  } finally {
    setRunning(false);
  }
}

function setRunning(running) {
  state.running = running;
  const button = $("#run-button");
  button.disabled = running;
  button.textContent = running ? "回测中…" : "运行回测";
}

// --------------------------------------------------------------------- report

function renderReport(report) {
  state.hasReport = true;
  const panel = $("#result-panel");
  panel.innerHTML = "";

  const spec = currentSpec(report.strategy);
  const head = document.createElement("div");
  head.className = "report-head";
  const title = document.createElement("h2");
  title.textContent = spec ? spec.title : report.strategy;
  const meta = document.createElement("span");
  meta.className = "report-meta";
  meta.textContent = `${report.symbols.join(" / ")} · ${fmtTime(report.start)} → ${fmtTime(report.end)} · ${report.bars_processed.toLocaleString()} bars`;
  head.appendChild(title);
  head.appendChild(meta);
  panel.appendChild(head);

  const sub = document.createElement("div");
  sub.className = "report-sub";
  const equityNow = report.metrics?.final_equity ?? report.final_equity;
  sub.innerHTML = `初始资金 <b>${escapeHtml(fmtMoney(report.initial_cash))}</b> → 期末权益 <b>${escapeHtml(fmtMoney(equityNow))}</b>`;
  panel.appendChild(sub);

  const params = document.createElement("div");
  params.className = "params-line";
  params.textContent = Object.entries(report.params || {})
    .map(([key, value]) => `${key}=${value}`)
    .join("  ");
  panel.appendChild(params);

  panel.appendChild(renderMetrics(report.metrics || {}));

  panel.appendChild(
    sectionTitle("权益曲线", `${report.equity_curve.length} 个采样点（UTC）`)
  );
  panel.appendChild(chart(report.equity_curve, { color: "#34d399", label: "equity" }));

  panel.appendChild(sectionTitle("回撤", "水下曲线，单位 %"));
  panel.appendChild(
    chart(report.drawdown_curve, {
      color: "#f87171",
      label: "drawdown",
      includeZero: true,
      suffix: "%",
      decimals: 2,
    })
  );

  if (report.monthly_returns && Object.keys(report.monthly_returns).length > 0) {
    panel.appendChild(sectionTitle("月度收益", "按 UTC 月末权益计算"));
    panel.appendChild(monthlyTable(report.monthly_returns));
  }

  const trades = report.trades || [];
  panel.appendChild(
    sectionTitle(
      "成交记录",
      `显示最近 ${trades.length} 笔 / 共 ${report.trades_total ?? trades.length} 笔`
    )
  );
  panel.appendChild(tradesTable(trades));

  const foot = document.createElement("div");
  foot.className = "report-foot";
  foot.textContent = `报告文件：${report.report_dir || "-"}`;
  panel.appendChild(foot);
}

function renderMetrics(metrics) {
  const grid = document.createElement("div");
  grid.className = "metrics";

  for (const [key, label, kind] of METRIC_ROWS) {
    if (!(key in metrics)) continue;
    const value = metrics[key];
    const card = document.createElement("div");
    card.className = "metric";

    const k = document.createElement("div");
    k.className = "k";
    k.textContent = label;

    const v = document.createElement("div");
    v.className = "v";
    v.textContent = valueFor(kind, value);

    if (value == null) {
      v.classList.add("na");
    } else if (kind === "pct" || kind === "money") {
      if (value > 0) v.classList.add("pos");
      if (value < 0) v.classList.add("neg");
    }

    card.appendChild(k);
    card.appendChild(v);
    grid.appendChild(card);
  }
  return grid;
}

function sectionTitle(text, aside) {
  const div = document.createElement("div");
  div.className = "section-title";
  div.appendChild(document.createTextNode(text));
  if (aside) {
    const span = document.createElement("span");
    span.textContent = aside;
    div.appendChild(span);
  }
  return div;
}

function monthlyTable(returns) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>月份</th><th>收益率</th></tr></thead>";
  const tbody = document.createElement("tbody");

  for (const [month, value] of Object.entries(returns)) {
    const row = document.createElement("tr");
    const monthCell = document.createElement("td");
    monthCell.textContent = month;
    const valueCell = document.createElement("td");
    valueCell.textContent = fmtPct(value);
    if (value > 0) valueCell.className = "pos";
    if (value < 0) valueCell.className = "neg";
    row.appendChild(monthCell);
    row.appendChild(valueCell);
    tbody.appendChild(row);
  }

  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function tradesTable(trades) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.innerHTML =
    "<thead><tr><th>时间 (UTC)</th><th>方向</th><th>数量</th><th>价格</th><th>手续费</th><th>已实现盈亏</th><th>原因</th></tr></thead>";
  const tbody = document.createElement("tbody");

  for (const trade of [...trades].reverse()) {
    const row = document.createElement("tr");

    const time = document.createElement("td");
    time.textContent = fmtTime(trade.time);

    const side = document.createElement("td");
    side.textContent = trade.side === "buy" ? "买入" : "卖出";
    side.className = trade.side === "buy" ? "side-buy" : "side-sell";

    const qty = document.createElement("td");
    qty.textContent = fmtQty(trade.qty);

    const price = document.createElement("td");
    price.textContent = fmtPrice(trade.price);

    const fee = document.createElement("td");
    fee.textContent = fmtMoney(trade.fee);

    const pnl = document.createElement("td");
    const realized = trade.realized_pnl || 0;
    pnl.textContent = realized === 0 ? "-" : `${realized > 0 ? "+" : ""}${fmtMoney(realized)}`;
    if (realized > 0) pnl.className = "pos";
    if (realized < 0) pnl.className = "neg";

    const reason = document.createElement("td");
    reason.textContent = trade.reason || "-";

    row.append(time, side, qty, price, fee, pnl, reason);
    tbody.appendChild(row);
  }

  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

// ---------------------------------------------------------------------- chart

function chart(points, options) {
  const wrap = document.createElement("div");
  wrap.className = "chart";

  if (!points || points.length === 0) {
    wrap.innerHTML = '<p class="hint">无数据</p>';
    return wrap;
  }

  const width = 960;
  const height = 250;
  const pad = { left: 68, right: 16, top: 14, bottom: 28 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const values = points.map((point) => point.v).filter(Number.isFinite);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (options.includeZero) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  min -= span * 0.08;
  max += span * 0.08;

  const xAt = (index) =>
    pad.left + (points.length === 1 ? plotW / 2 : (index / (points.length - 1)) * plotW);
  const yAt = (value) => pad.top + ((max - value) / (max - min)) * plotH;

  const linePoints = points
    .map((point, index) => `${xAt(index).toFixed(1)},${yAt(point.v).toFixed(1)}`)
    .join(" ");

  const baseY = pad.top + plotH;
  const areaPath = `M ${xAt(0).toFixed(1)} ${baseY.toFixed(1)} L ${linePoints.replaceAll(
    " ",
    " L "
  )} L ${xAt(points.length - 1).toFixed(1)} ${baseY.toFixed(1)} Z`;

  const gradientId = `grad-${options.label}-${Math.random().toString(36).slice(2, 8)}`;
  const parts = [
    `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(options.label)}">`,
    `<defs><linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1">`,
    `<stop offset="0%" stop-color="${options.color}" stop-opacity="0.28"/>`,
    `<stop offset="100%" stop-color="${options.color}" stop-opacity="0"/>`,
    `</linearGradient></defs>`,
  ];

  for (let step = 0; step <= 4; step += 1) {
    const value = max - ((max - min) * step) / 4;
    const y = yAt(value);
    parts.push(
      `<line class="grid" x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}"/>`
    );
    parts.push(
      `<text x="${pad.left - 8}" y="${(y + 3).toFixed(1)}" text-anchor="end">${formatAxis(
        value,
        options
      )}</text>`
    );
  }

  if (options.includeZero && 0 >= min && 0 <= max) {
    const zeroY = yAt(0);
    parts.push(
      `<line class="grid" x1="${pad.left}" y1="${zeroY.toFixed(1)}" x2="${width - pad.right}" y2="${zeroY.toFixed(
        1
      )}" stroke-dasharray="4 4"/>`
    );
  }

  parts.push(`<path d="${areaPath}" fill="url(#${gradientId})" stroke="none"/>`);
  parts.push(
    `<polyline points="${linePoints}" fill="none" stroke="${options.color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>`
  );

  const first = points[0].t;
  const last = points[points.length - 1].t;
  parts.push(
    `<text x="${pad.left}" y="${height - 8}" text-anchor="start">${escapeHtml(fmtTime(first))}</text>`
  );
  parts.push(
    `<text x="${width - pad.right}" y="${height - 8}" text-anchor="end">${escapeHtml(fmtTime(last))}</text>`
  );
  parts.push("</svg>");

  wrap.innerHTML = parts.join("");
  return wrap;
}

function formatAxis(value, options) {
  if (options.suffix === "%") return `${value.toFixed(2)}%`;
  const abs = Math.abs(value);
  if (abs >= 1000) return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return value.toFixed(abs >= 10 ? 2 : 4);
}

// ------------------------------------------------------------------- feedback

function showError(message) {
  clearBanner();
  const panel = $("#result-panel");
  const banner = document.createElement("div");
  banner.className = "banner";
  banner.id = "error-banner";
  banner.textContent = message;
  panel.prepend(banner);
  if (!state.hasReport) {
    panel.querySelector("#empty-state")?.classList.add("hidden");
  }
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearBanner() {
  $("#error-banner")?.remove();
  if (!state.hasReport) {
    $("#empty-state")?.classList.remove("hidden");
  }
}

// ------------------------------------------------------------------- wire up

$("#backtest-form").addEventListener("submit", submit);
boot();
