// ---------- タブ切替 ----------
const tabs = document.querySelectorAll(".tab");
const views = document.querySelectorAll(".view");

function switchView(name) {
  views.forEach(v => v.hidden = v.dataset.view !== name);
  tabs.forEach(t => t.classList.toggle("active", t.dataset.view === name));
  if (name === "trades") loadTrades();
  if (name === "stats") loadStatistics();
}

tabs.forEach(tab => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});

// ---------- API接続確認 ----------
async function checkApiStatus() {
  const dot = document.getElementById("apiDot");
  const text = document.getElementById("apiStatusText");
  try {
    await Api.healthCheck();
    dot.className = "dot ok";
    text.textContent = "接続OK";
  } catch (e) {
    dot.className = "dot err";
    text.textContent = "未接続";
  }
}

// ---------- ①チャート分析 ----------
const chartFileInput = document.getElementById("chartFileInput");
const uploadDrop = document.getElementById("uploadDrop");
const chartPreview = document.getElementById("chartPreview");
const analyzeBtn = document.getElementById("analyzeBtn");
const analysisResult = document.getElementById("analysisResult");

let selectedFile = null;

uploadDrop.addEventListener("click", () => chartFileInput.click());

chartFileInput.addEventListener("change", () => {
  const file = chartFileInput.files[0];
  if (!file) return;
  selectedFile = file;
  const url = URL.createObjectURL(file);
  chartPreview.src = url;
  chartPreview.hidden = false;
  analyzeBtn.hidden = false;
  analysisResult.hidden = true;
});

const DIRECTION_LABEL = { long: "ロング", short: "ショート", skip: "見送り" };

function renderAnalysis(result) {
  const dir = result.direction || "skip";
  const badgeClass = dir === "long" ? "long" : dir === "short" ? "short" : "skip";

  let html = `
    <div class="result-header">
      <span>${result.currency_pair || "通貨ペア不明"}</span>
      <span class="direction-badge ${badgeClass}">${DIRECTION_LABEL[dir] || dir}</span>
    </div>
  `;

  if (dir !== "skip") {
    html += `
      <div class="metric-row"><span class="label">エントリー</span><span class="value">${fmt(result.entry_price)}</span></div>
      <div class="metric-row"><span class="label">損切り</span><span class="value">${fmt(result.stop_loss)}</span></div>
      <div class="metric-row"><span class="label">利確目標</span><span class="value">${fmt(result.take_profit)}</span></div>
      <div class="metric-row"><span class="label">リスクリワード</span><span class="value">${fmt(result.risk_reward)}</span></div>
    `;
  }

  const reasonText = dir === "skip" ? result.skip_reason : result.entry_reason;
  if (reasonText) {
    html += `<div class="reason-block"><span class="k">${dir === "skip" ? "見送り理由" : "エントリー根拠"}</span>${escapeHtml(reasonText)}</div>`;
  }

  const fields = [
    ["トレンド", result.trend],
    ["サポート・レジスタンス", result.support_resistance],
    ["ダウ理論", result.dow_theory],
    ["ローソク足パターン", result.candle_pattern],
    ["移動平均線", result.moving_average],
    ["RSI/MACD", result.rsi_macd],
    ["ボラティリティ", result.volatility],
  ];
  fields.forEach(([label, value]) => {
    if (value) html += `<div class="reason-block"><span class="k">${label}</span>${escapeHtml(value)}</div>`;
  });

  analysisResult.innerHTML = html;
  analysisResult.hidden = false;
}

analyzeBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "分析中...";
  try {
    const result = await Api.analyzeChart(selectedFile);
    renderAnalysis(result);
    loadAnalysisHistory();
  } catch (e) {
    analysisResult.hidden = false;
    analysisResult.innerHTML = `<div class="reason-block">${escapeHtml(e.message)}</div>`;
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "この画像を分析する";
  }
});

async function loadAnalysisHistory() {
  const container = document.getElementById("analysisHistory");
  try {
    const items = await Api.listAnalyses();
    if (!items.length) {
      container.innerHTML = `<div class="empty-state">まだ分析履歴がありません</div>`;
      return;
    }
    container.innerHTML = items.map(a => {
      const dir = a.direction || "skip";
      const badgeClass = dir === "long" ? "long" : dir === "short" ? "short" : "skip";
      return `
        <div class="list-item">
          <div class="top-row">
            <span class="pair">${a.currency_pair || "-"}</span>
            <span class="direction-badge ${badgeClass}">${DIRECTION_LABEL[dir] || dir}</span>
          </div>
          <div class="meta">${formatDate(a.created_at)}</div>
        </div>
      `;
    }).join("");
  } catch (e) {
    container.innerHTML = `<div class="empty-state">履歴を取得できませんでした</div>`;
  }
}

// ---------- ②トレード記録(画像から自動読み取り) ----------
const tradeImageInput = document.getElementById("tradeImageInput");
const tradeUploadDrop = document.getElementById("tradeUploadDrop");
const tradeImagePreview = document.getElementById("tradeImagePreview");
const tradeAnalyzeBtn = document.getElementById("tradeAnalyzeBtn");
const tradeImportResult = document.getElementById("tradeImportResult");

let selectedTradeImage = null;

tradeUploadDrop.addEventListener("click", () => tradeImageInput.click());

tradeImageInput.addEventListener("change", () => {
  const file = tradeImageInput.files[0];
  if (!file) return;
  selectedTradeImage = file;
  tradeImagePreview.src = URL.createObjectURL(file);
  tradeImagePreview.hidden = false;
  tradeAnalyzeBtn.hidden = false;
  tradeImportResult.hidden = true;
});

tradeAnalyzeBtn.addEventListener("click", async () => {
  if (!selectedTradeImage) return;
  tradeAnalyzeBtn.disabled = true;
  tradeAnalyzeBtn.textContent = "読み取り中...";
  try {
    const result = await Api.createTradesFromImage(selectedTradeImage);
    tradeImportResult.hidden = false;
    tradeImportResult.innerHTML = `
      <div class="reason-block">
        <span class="k">結果</span>
        ${result.created_count}件の記録を追加しました${result.skipped_count ? `(${result.skipped_count}件は情報不足のためスキップ)` : ""}
      </div>
    `;
    loadTrades();
  } catch (e) {
    tradeImportResult.hidden = false;
    tradeImportResult.innerHTML = `<div class="reason-block">${escapeHtml(e.message)}</div>`;
  } finally {
    tradeAnalyzeBtn.disabled = false;
    tradeAnalyzeBtn.textContent = "この画像から記録を読み取る";
  }
});

// ---------- ②トレード記録 ----------
const tradeForm = document.getElementById("tradeForm");

tradeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(tradeForm);
  const payload = {};
  for (const [key, value] of formData.entries()) {
    if (value === "") continue;
    if (["entry_price", "exit_price", "profit_loss", "lot_size"].includes(key)) {
      payload[key] = parseFloat(value);
    } else {
      payload[key] = value;
    }
  }
  try {
    await Api.createTrade(payload);
    tradeForm.reset();
    loadTrades();
  } catch (e) {
    alert(e.message);
  }
});

async function loadTrades() {
  const container = document.getElementById("tradesList");
  try {
    const trades = await Api.listTrades();
    if (!trades.length) {
      container.innerHTML = `<div class="empty-state">まだ記録がありません</div>`;
      return;
    }
    container.innerHTML = trades.map(t => {
      const pl = t.profit_loss;
      const plClass = pl > 0 ? "pos" : pl < 0 ? "neg" : "";
      return `
        <div class="list-item">
          <div class="top-row">
            <span class="pair">${t.currency_pair}</span>
            <span class="pl ${plClass}">${pl != null ? (pl > 0 ? "+" : "") + pl : "-"}</span>
          </div>
          <div class="meta">${fmt(t.entry_price)} → ${fmt(t.exit_price)} ・ ${formatDate(t.entry_datetime)}</div>
        </div>
      `;
    }).join("");
  } catch (e) {
    container.innerHTML = `<div class="empty-state">記録を取得できませんでした</div>`;
  }
}

// ---------- ③統計・改善提案 ----------
async function loadStatistics() {
  const grid = document.getElementById("statsGrid");
  const breakdown = document.getElementById("statsBreakdown");
  try {
    const stats = await Api.getStatistics();
    grid.innerHTML = `
      <div class="stat-box"><div class="num">${stats.total_trades}</div><div class="lbl">総トレード数</div></div>
      <div class="stat-box"><div class="num">${fmtPct(stats.win_rate)}</div><div class="lbl">勝率</div></div>
      <div class="stat-box"><div class="num">${stats.profit_factor ?? "-"}</div><div class="lbl">プロフィットファクター</div></div>
      <div class="stat-box"><div class="num">${stats.max_drawdown ?? "-"}</div><div class="lbl">最大ドローダウン</div></div>
      <div class="stat-box"><div class="num">${stats.max_winning_streak}</div><div class="lbl">最大連勝</div></div>
      <div class="stat-box"><div class="num">${stats.max_losing_streak}</div><div class="lbl">最大連敗</div></div>
    `;

    const pairs = Object.entries(stats.by_currency_pair || {});
    breakdown.innerHTML = pairs.length
      ? pairs.map(([pair, s]) => `
          <div class="list-item">
            <div class="top-row"><span class="pair">${pair}</span><span>${fmtPct(s.win_rate)}</span></div>
            <div class="meta">${s.trade_count}件 ・ 損益合計 ${s.total_profit_loss}</div>
          </div>
        `).join("")
      : `<div class="empty-state">通貨ペア別データがありません</div>`;
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">統計を取得できませんでした</div>`;
  }
}

document.getElementById("improvementBtn").addEventListener("click", async () => {
  const btn = document.getElementById("improvementBtn");
  const result = document.getElementById("improvementResult");
  btn.disabled = true;
  btn.textContent = "生成中...";
  try {
    const data = await Api.getImprovement();
    const s = data.suggestions || {};
    const section = (title, items) => (items && items.length)
      ? `<div class="reason-block"><span class="k">${title}</span>${items.map(escapeHtml).join(" / ")}</div>`
      : "";
    result.innerHTML = [
      section("勝率が高いパターン", s.winning_patterns),
      section("勝率が低いパターン", s.losing_patterns),
      section("エントリー改善案", s.entry_improvements),
      section("損切り改善案", s.stop_loss_improvements),
      section("利確改善案", s.take_profit_improvements),
      section("避けるべき相場", s.avoid_conditions),
    ].join("");
    result.hidden = false;
  } catch (e) {
    result.hidden = false;
    result.innerHTML = `<div class="reason-block">${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "AIに改善提案をもらう";
  }
});

// ---------- ユーティリティ ----------
function fmt(n) {
  return (n === null || n === undefined) ? "-" : n;
}
function fmtPct(n) {
  return (n === null || n === undefined) ? "-" : `${n}%`;
}
function formatDate(d) {
  if (!d) return "-";
  const date = new Date(d);
  return date.toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------- 初期化 ----------
checkApiStatus();
loadAnalysisHistory();

// Service Worker登録(PWA化)
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}
