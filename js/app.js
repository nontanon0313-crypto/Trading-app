// ---------- タブ切替 ----------
const tabs = document.querySelectorAll(".tab");
const views = document.querySelectorAll(".view");

function switchView(name) {
  views.forEach(v => v.hidden = v.dataset.view !== name);
  tabs.forEach(t => t.classList.toggle("active", t.dataset.view === name));
  if (name === "trades") loadTrades();
  if (name === "stats") { loadStatistics(); loadCalendar(); loadHypotheses(); }
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

// ---------- ①チャート分析(マルチタイムフレーム) ----------
const analyzeBtn = document.getElementById("analyzeBtn");
const analysisResult = document.getElementById("analysisResult");

const mtfSlots = Array.from(document.querySelectorAll(".mtf-slot")).map(slotEl => ({
  el: slotEl,
  tfSelect: slotEl.querySelector(".mtf-tf-select"),
  drop: slotEl.querySelector(".mtf-drop"),
  preview: slotEl.querySelector(".mtf-preview"),
  file: null,
}));

mtfSlots.forEach(slot => {
  slot.drop.addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.addEventListener("change", () => {
      const file = input.files[0];
      if (!file) return;
      slot.file = file;
      slot.preview.src = URL.createObjectURL(file);
      slot.preview.hidden = false;
      slot.drop.querySelector("p").textContent = file.name;
      analysisResult.hidden = true;
      analyzeBtn.hidden = !mtfSlots.some(s => s.file);
    });
    input.click();
  });
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

  if (Array.isArray(result.scenario_forecast) && result.scenario_forecast.length) {
    html += `<div class="reason-block"><span class="k">シナリオ予測</span>`;
    html += result.scenario_forecast.map(s =>
      `${escapeHtml(s.condition || "")}: ${escapeHtml(s.expected_move || "")}${s.target_level ? "(目安: " + escapeHtml(String(s.target_level)) + ")" : ""}${s.confidence != null ? " [確信度" + s.confidence + "%]" : ""}`
    ).join("<br>");
    html += `</div>`;
  }

  if (result.agreement_points) {
    html += `<div class="reason-block"><span class="k">タグ間の一致点</span>${escapeHtml(result.agreement_points)}</div>`;
  }
  if (result.conflict_points) {
    html += `<div class="reason-block"><span class="k">タグ間の矛盾点</span>${escapeHtml(result.conflict_points)}</div>`;
  }

  const evals = result.tag_evaluations;
  if (Array.isArray(evals) && evals.length) {
    const yesTags = evals.filter(e => e.judgment === "yes").sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    html += `<div class="reason-block"><span class="k">該当タグ(確信度順)</span>`;
    html += yesTags.length
      ? yesTags.map(e => `${escapeHtml(e.tag)}(${e.confidence ?? "-"}%・${e.direction_impact || "-"})`).join(" / ")
      : "該当タグなし";
    html += `</div>`;
  }

  analysisResult.innerHTML = html;
  analysisResult.hidden = false;
}

analyzeBtn.addEventListener("click", async () => {
  const slotsWithFiles = mtfSlots.filter(s => s.file);
  if (!slotsWithFiles.length) return;
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "分析中...";
  try {
    const payload = mtfSlots.map(s => ({ file: s.file, timeframe: s.tfSelect.value }));
    const result = await Api.analyzeChart(payload);
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
    container.innerHTML = items.map((a, idx) => {
      const dir = a.direction || "skip";
      const badgeClass = dir === "long" ? "long" : dir === "short" ? "short" : "skip";
      return `
        <div class="list-item" data-idx="${idx}">
          <div class="top-row">
            <span class="pair">${a.currency_pair || "-"}</span>
            <span class="direction-badge ${badgeClass}">${DIRECTION_LABEL[dir] || dir}</span>
          </div>
          <div class="meta">${formatDate(a.created_at)}</div>
        </div>
      `;
    }).join("") + `<div class="result-card" id="historyScenarioDetail" hidden></div>`;

    container.querySelectorAll(".list-item[data-idx]").forEach(el => {
      el.addEventListener("click", () => {
        const item = items[parseInt(el.dataset.idx, 10)];
        const detail = document.getElementById("historyScenarioDetail");
        const scenarios = item.scenario_forecast;
        detail.hidden = false;
        detail.innerHTML = (Array.isArray(scenarios) && scenarios.length)
          ? `<div class="reason-block"><span class="k">シナリオ予測</span>` +
            scenarios.map(s =>
              `${escapeHtml(s.condition || "")}: ${escapeHtml(s.expected_move || "")}${s.target_level ? "(目安: " + escapeHtml(String(s.target_level)) + ")" : ""}${s.confidence != null ? " [確信度" + s.confidence + "%]" : ""}`
            ).join("<br>") + `</div>`
          : `<div class="reason-block">この分析にはシナリオ予測がありません</div>`;
        detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-state">履歴を取得できませんでした</div>`;
  }
}

// ---------- ②エントリー即時記録 ----------
const pairSelect = document.getElementById("quickEntryPairSelect");
const pairNewInput = document.getElementById("quickEntryPairNew");

async function loadCurrencyPairOptions() {
  try {
    const pairs = await Api.getCurrencyPairs();
    pairSelect.innerHTML = pairs.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("")
      + `<option value="__new__">+ 新しい通貨ペアを入力</option>`;
  } catch (e) {
    pairSelect.innerHTML = `<option value="__new__">+ 新しい通貨ペアを入力</option>`;
  }
  // 選択肢が「新規入力」しか無い場合、changeイベントが発火しないため手動で入力欄を出す
  pairNewInput.hidden = pairSelect.value !== "__new__";
}
loadCurrencyPairOptions();

pairSelect.addEventListener("change", () => {
  pairNewInput.hidden = pairSelect.value !== "__new__";
});

document.getElementById("quickEntryForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  const currencyPair = pairSelect.value === "__new__" ? pairNewInput.value.trim() : pairSelect.value;
  if (!currencyPair) { alert("通貨ペアを入力してください"); return; }

  const payload = {
    currency_pair: currencyPair,
    side: formData.get("side"),
    entry_price: parseFloat(formData.get("entry_price")),
    entry_datetime: localNowString(),
  };
  const lot = formData.get("lot_size");
  if (lot) payload.lot_size = parseFloat(lot);

  try {
    const trade = await Api.createTrade(payload);
    e.target.reset();
    pairNewInput.hidden = true;
    pairNewInput.value = "";
    loadCurrencyPairOptions();
    loadTrades();
    openJournalModal(trade.id);
  } catch (err) {
    alert(err.message);
  }
});

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

let previewItems = [];

tradeAnalyzeBtn.addEventListener("click", async () => {
  if (!selectedTradeImage) return;
  tradeAnalyzeBtn.disabled = true;
  tradeAnalyzeBtn.textContent = "読み取り中...";
  try {
    const result = await Api.previewTradesFromImage(selectedTradeImage);
    previewItems = result.items || [];
    renderImportPreview(result.skipped_count);
  } catch (e) {
    tradeImportResult.hidden = false;
    tradeImportResult.innerHTML = `<div class="reason-block">${escapeHtml(e.message)}</div>`;
  } finally {
    tradeAnalyzeBtn.disabled = false;
    tradeAnalyzeBtn.textContent = "この画像から記録を読み取る";
  }
});

function renderImportPreview(skippedCount) {
  const previewBox = document.getElementById("tradeImportPreview");
  const list = document.getElementById("tradeImportPreviewList");

  if (!previewItems.length) {
    tradeImportResult.hidden = false;
    tradeImportResult.innerHTML = `<div class="reason-block">取り込める決済データが見つかりませんでした${skippedCount ? `(${skippedCount}件は情報不足のためスキップ)` : ""}</div>`;
    previewBox.hidden = true;
    return;
  }

  list.innerHTML = previewItems.map((item, idx) => {
    const options = [`<option value="new">新規作成として登録</option>`]
      .concat((item.candidates || []).map(c => {
        const label = `#${c.id}: ${fmt(c.entry_price)} ・ ${formatDate(c.entry_datetime)}${c.journal_entry_reason ? " ・ " + c.journal_entry_reason.slice(0, 20) : ""}`;
        const selected = item.suggested_trade_id === c.id ? "selected" : "";
        return `<option value="${c.id}" ${selected}>${escapeHtml(label)}に対応させる</option>`;
      }))
      .join("");
    return `
      <div class="list-item">
        <div class="top-row">
          <span class="pair">${item.currency_pair || "-"}</span>
          <span class="pl ${item.profit_loss > 0 ? "pos" : "neg"}">${item.profit_loss != null ? (item.profit_loss > 0 ? "+" : "") + item.profit_loss : "-"}</span>
        </div>
        <div class="meta">${fmt(item.entry_price)} → ${fmt(item.exit_price)} ・ ${formatDate(item.exit_datetime)}</div>
        <select class="preview-match-select" data-idx="${idx}">${options}</select>
      </div>
    `;
  }).join("");

  if (skippedCount) {
    list.innerHTML += `<div class="empty-state">${skippedCount}件は情報不足のためスキップされます</div>`;
  }

  previewBox.hidden = false;
  tradeImportResult.hidden = true;
}

document.getElementById("confirmImportBtn").addEventListener("click", async () => {
  const btn = document.getElementById("confirmImportBtn");
  const selects = document.querySelectorAll(".preview-match-select");
  const items = Array.from(selects).map(sel => {
    const item = previewItems[parseInt(sel.dataset.idx, 10)];
    const chosen = sel.value;
    return {
      trade_id: chosen === "new" ? null : parseInt(chosen, 10),
      currency_pair: item.currency_pair,
      side: item.side,
      entry_price: item.entry_price,
      exit_price: item.exit_price,
      profit_loss: item.profit_loss,
      lot_size: item.lot_size,
      entry_datetime: item.entry_datetime,
      exit_datetime: item.exit_datetime,
    };
  });

  btn.disabled = true;
  btn.textContent = "取り込み中...";
  try {
    const result = await Api.confirmTradesFromImage(items);
    document.getElementById("tradeImportPreview").hidden = true;
    tradeImportResult.hidden = false;
    tradeImportResult.innerHTML = `<div class="reason-block"><span class="k">結果</span>新規${result.created_count}件・紐付け${result.matched_count}件を反映しました</div>`;
    previewItems = [];
    loadTrades();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "この内容で取り込みを確定する";
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
      const hasJournal = t.journal_entry_reason || t.journal_post_notes;
      const isOpen = t.exit_price == null;
      return `
        <div class="list-item">
          <div class="top-row">
            <span class="pair">#${t.id} ${t.currency_pair}${hasJournal ? " 📝" : ""}${isOpen ? ' <span class="direction-badge skip">保有中</span>' : ""}</span>
            <span class="pl ${plClass}">${pl != null ? (pl > 0 ? "+" : "") + pl : "-"}</span>
          </div>
          <div class="meta">${fmt(t.entry_price)} → ${fmt(t.exit_price)}${t.return_pct != null ? ` (${t.return_pct > 0 ? "+" : ""}${t.return_pct}%)` : ""} ・ ${formatDate(t.entry_datetime)}</div>
          <button class="btn btn-secondary journal-btn" data-trade-id="${t.id}">${hasJournal ? "日記を編集" : "日記を書く"}</button>
        </div>
      `;
    }).join("");
    container.querySelectorAll(".journal-btn").forEach(btn => {
      btn.addEventListener("click", () => openJournalModal(btn.dataset.tradeId));
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-state">記録を取得できませんでした</div>`;
  }
}

// ---------- トレード日記モーダル ----------
const journalModal = document.getElementById("journalModal");
const journalForm = document.getElementById("journalForm");
let currentJournalTradeId = null;

let linkedAnalysisData = null;
let selectedTags = new Set();
let ruleTagLibrary = {};

function renderTagPicker() {
  const container = document.getElementById("ruleTagsPicker");
  const categories = Object.keys(ruleTagLibrary);
  if (!categories.length) {
    container.innerHTML = `<span class="hint">タグライブラリが空です</span>`;
    return;
  }
  container.innerHTML = categories.map(cat => `
    <div>
      <div class="tag-cat-label">${escapeHtml(cat)}</div>
      <div class="tag-chips">
        ${ruleTagLibrary[cat].map(t => `
          <button type="button" class="tag-chip ${selectedTags.has(t.name) ? "selected" : ""}" data-tag="${escapeHtml(t.name)}">${escapeHtml(t.name)}</button>
        `).join("")}
      </div>
    </div>
  `).join("");

  container.querySelectorAll(".tag-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const tag = chip.dataset.tag;
      if (selectedTags.has(tag)) selectedTags.delete(tag);
      else selectedTags.add(tag);
      chip.classList.toggle("selected");
    });
  });
}

document.getElementById("addTagBtn").addEventListener("click", async () => {
  const catInput = document.getElementById("newTagCategory");
  const nameInput = document.getElementById("newTagName");
  const category = catInput.value.trim();
  const name = nameInput.value.trim();
  if (!category || !name) { alert("カテゴリとタグ名を入力してください"); return; }
  try {
    await Api.addRuleTagToLibrary(category, name);
    ruleTagLibrary = await Api.getRuleTagLibrary();
    selectedTags.add(name);
    renderTagPicker();
    catInput.value = "";
    nameInput.value = "";
  } catch (e) {
    alert(e.message);
  }
});

async function openJournalModal(tradeId) {
  currentJournalTradeId = tradeId;
  try {
    const trade = await Api.getTrade(tradeId);
    journalForm.reset();
    Object.keys(trade).forEach(key => {
      const field = journalForm.elements[key];
      if (field && trade[key] != null) field.value = trade[key];
    });
    document.getElementById("journalModalTitle").textContent =
      `トレード日記 #${trade.id}${trade.return_pct != null ? ` (${trade.return_pct > 0 ? "+" : ""}${trade.return_pct}%)` : ""}`;
    document.getElementById("tradeReviewResult").hidden = true;

    document.getElementById("editCurrencyPair").value = trade.currency_pair || "";
    document.getElementById("editSide").value = trade.side || "buy";
    document.getElementById("editEntryPrice").value = trade.entry_price ?? "";
    document.getElementById("editExitPrice").value = trade.exit_price ?? "";
    document.getElementById("editProfitLoss").value = trade.profit_loss ?? "";
    document.getElementById("editLotSize").value = trade.lot_size ?? "";
    document.getElementById("editEntryDatetime").value = toDatetimeLocalValue(trade.entry_datetime);
    document.getElementById("editExitDatetime").value = toDatetimeLocalValue(trade.exit_datetime);

    selectedTags = new Set(Array.isArray(trade.journal_rule_tags) ? trade.journal_rule_tags : []);
    ruleTagLibrary = await Api.getRuleTagLibrary().catch(() => ({}));
    renderTagPicker();

    const precommitEl = document.getElementById("precommitStatus");
    if (!trade.journal_pre_committed_at) {
      precommitEl.innerHTML = `<span class="hint">まだエントリー前の記録なし</span>`;
    } else if (trade.is_precommitted) {
      precommitEl.innerHTML = `<span class="hint">✅ 事前記録あり(${formatDate(trade.journal_pre_committed_at)}、決済前に記録)</span>`;
    } else {
      precommitEl.innerHTML = `<span class="hint">⚠️ 決済後の記録(${formatDate(trade.journal_pre_committed_at)})- 後付けの可能性あり</span>`;
    }

    const select = document.getElementById("analysisSelect");
    try {
      const analyses = await Api.listAnalyses();
      select.innerHTML = analyses.length
        ? analyses.map(a =>
            `<option value="${a.id}">${formatDate(a.created_at)} ${a.currency_pair || ""} ${a.direction || ""}</option>`
          ).join("")
        : `<option value="">まだチャート分析の履歴がありません</option>`;
    } catch (e) {
      select.innerHTML = `<option value="">分析履歴を取得できませんでした</option>`;
    }

    linkedAnalysisData = await Api.getLinkedAnalysis(tradeId).catch(() => null);
    const label = document.getElementById("linkedAnalysisLabel");
    label.textContent = linkedAnalysisData
      ? `紐付け中: ${formatDate(linkedAnalysisData.created_at)} ${linkedAnalysisData.currency_pair || ""}`
      : "紐付けなし";

    journalModal.hidden = false;
  } catch (e) {
    alert(e.message);
  }
}

document.getElementById("linkAnalysisBtn").addEventListener("click", async () => {
  const select = document.getElementById("analysisSelect");
  if (!currentJournalTradeId) return;
  if (!select.value) { alert("紐付けるチャート分析がありません。先に「分析」タブでチャート画像を分析してください。"); return; }
  try {
    await Api.linkAnalysis(currentJournalTradeId, parseInt(select.value, 10));
    linkedAnalysisData = await Api.getLinkedAnalysis(currentJournalTradeId);
    document.getElementById("linkedAnalysisLabel").textContent =
      `紐付け中: ${formatDate(linkedAnalysisData.created_at)} ${linkedAnalysisData.currency_pair || ""}`;
    alert("紐付けました");
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("quoteAnalysisBtn").addEventListener("click", () => {
  if (!linkedAnalysisData) { alert("先にチャート分析を紐付けてください"); return; }
  if (linkedAnalysisData.entry_reason) journalForm.elements["journal_entry_reason"].value = linkedAnalysisData.entry_reason;
  if (linkedAnalysisData.trend) journalForm.elements["journal_scenario"].value = linkedAnalysisData.trend;
});

function localNowString() {
  const d = new Date();
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function toDatetimeLocalValue(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

document.getElementById("saveTradeInfoBtn").addEventListener("click", async () => {
  try {
    if (!currentJournalTradeId) { alert("トレードが選択されていません"); return; }
    const val = (id) => {
      const el = document.getElementById(id);
      if (!el) throw new Error(`要素が見つかりません: ${id}`);
      return el.value === "" ? null : el.value;
    };
    const payload = {
      currency_pair: val("editCurrencyPair"),
      side: val("editSide"),
      entry_price: val("editEntryPrice") != null ? parseFloat(val("editEntryPrice")) : null,
      exit_price: val("editExitPrice") != null ? parseFloat(val("editExitPrice")) : null,
      profit_loss: val("editProfitLoss") != null ? parseFloat(val("editProfitLoss")) : null,
      lot_size: val("editLotSize") != null ? parseFloat(val("editLotSize")) : null,
      entry_datetime: val("editEntryDatetime") != null ? val("editEntryDatetime") + ":00" : null,
      exit_datetime: val("editExitDatetime") != null ? val("editExitDatetime") + ":00" : null,
    };
    // nullのキーは送らない(未入力のまま上書きしてしまうのを防ぐ)
    Object.keys(payload).forEach(k => { if (payload[k] === null) delete payload[k]; });
    await Api.updateTradeInfo(currentJournalTradeId, payload);
    loadTrades();
    alert("基本情報を保存しました");
  } catch (e) {
    alert("エラー: " + e.message);
  }
});

document.getElementById("deleteTradeBtn").addEventListener("click", async () => {
  try {
    if (!currentJournalTradeId) return;
    if (!confirm("このトレード記録を削除します。元に戻せません。よろしいですか?")) return;
    await Api.deleteTrade(currentJournalTradeId);
    journalModal.hidden = true;
    loadTrades();
  } catch (e) {
    alert("エラー: " + e.message);
  }
});

document.getElementById("journalModalClose").addEventListener("click", () => {
  journalModal.hidden = true;
});
journalModal.addEventListener("click", (e) => {
  if (e.target === journalModal) journalModal.hidden = true;
});

journalForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentJournalTradeId) return;
  const formData = new FormData(journalForm);
  const payload = {};
  for (const [key, value] of formData.entries()) {
    if (value === "") continue;
    payload[key] = key === "journal_confidence" || key === "journal_planned_take_profit"
      ? parseFloat(value)
      : value;
  }
  payload.journal_rule_tags = Array.from(selectedTags);
  try {
    await Api.updateTradeJournal(currentJournalTradeId, payload);
    journalModal.hidden = true;
    loadTrades();
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("tradeReviewBtn").addEventListener("click", async () => {
  if (!currentJournalTradeId) return;
  const btn = document.getElementById("tradeReviewBtn");
  const result = document.getElementById("tradeReviewResult");
  btn.disabled = true;
  btn.textContent = "分析中...";
  try {
    const data = await Api.reviewTrade(currentJournalTradeId);
    const r = data.review || {};
    const section = (title, obj) => {
      if (!obj || typeof obj !== "object") return "";
      const lines = Object.values(obj).filter(Boolean).join(" / ");
      return lines ? `<div class="reason-block"><span class="k">${title}</span>${escapeHtml(lines)}</div>` : "";
    };
    result.hidden = false;
    result.innerHTML = [
      section("エントリー分析", r.entry_analysis),
      section("リスク分析", r.risk_analysis),
      section("決済分析", r.exit_analysis),
      section("心理分析", r.psychology_analysis),
      section("チャート分析", r.chart_analysis),
      r.summary ? `<div class="reason-block"><span class="k">総合コメント</span>${escapeHtml(r.summary)}</div>` : "",
    ].join("");
  } catch (e) {
    result.hidden = false;
    result.innerHTML = `<div class="reason-block">${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "AIに5カテゴリでレビューしてもらう";
  }
});

// ---------- ③統計・改善提案 ----------
async function loadStatistics() {
  const grid = document.getElementById("statsGrid");
  const breakdown = document.getElementById("statsBreakdown");
  try {
    const stats = await Api.getStatistics();
    grid.innerHTML = `
      <div class="stat-box"><div class="num">${stats.total_trades}</div><div class="lbl">総トレード数</div></div>
      <div class="stat-box"><div class="num">${fmtPct(stats.win_rate)}</div><div class="lbl">勝率</div></div>
      <div class="stat-box"><div class="num">${stats.profit_factor ?? (stats.total_trades > 0 ? "∞(負けなし)" : "-")}</div><div class="lbl">プロフィットファクター</div></div>
      <div class="stat-box"><div class="num">${stats.max_drawdown ?? "-"}</div><div class="lbl">最大ドローダウン</div></div>
      <div class="stat-box"><div class="num">${stats.max_winning_streak}</div><div class="lbl">最大連勝</div></div>
      <div class="stat-box"><div class="num">${stats.max_losing_streak}</div><div class="lbl">最大連敗</div></div>
      <div class="stat-box"><div class="num">${stats.expectancy_pct != null ? stats.expectancy_pct + "%" : "-"}</div><div class="lbl">期待値(証拠金対比%・レバレッジ込み)</div></div>
      <div class="stat-box"><div class="num">${fmtPct(stats.precommit_rate)}</div><div class="lbl">事前記録率</div></div>
      <div class="stat-box"><div class="num">${stats.average_holding_minutes ?? "-"}</div><div class="lbl">平均保有時間(分)</div></div>
      <div class="stat-box"><div class="num">${fmtPct(stats.rule_adherence_rate)}</div><div class="lbl">ルール遵守率</div></div>
    `;

    const renderGroup = (title, obj) => {
      const entries = Object.entries(obj || {});
      if (!entries.length) return "";
      return `
        <h3 class="modal-section-title">${title}</h3>
        ${entries.map(([k, s]) => `
          <div class="list-item">
            <div class="top-row"><span class="pair">${k}</span><span>${fmtPct(s.win_rate)}</span></div>
            <div class="meta">${s.trade_count}件 ・ 損益合計 ${s.total_profit_loss} ・ 期待値 ${s.expectancy_pct != null ? s.expectancy_pct + "%" : "-"}</div>
          </div>
        `).join("")}
      `;
    };

    breakdown.innerHTML = [
      renderGroup("通貨ペア別", stats.by_currency_pair),
      renderGroup("ロング/ショート別", stats.by_side),
      renderGroup("ルールタグ別", stats.by_rule_tag),
      renderGroup("時間帯別", stats.by_hour),
      renderGroup("曜日別", stats.by_weekday),
      renderGroup("エントリー理由別", stats.by_entry_reason),
      renderGroup("利確/損切り理由別", stats.by_exit_reason),
      renderGroup("感情別", stats.by_emotion),
      renderGroup("確信度別", stats.by_confidence),
    ].join("") || `<div class="empty-state">データがありません</div>`;
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

// ---------- 日別カレンダーヒートマップ ----------
let calendarData = {};
let calViewDate = new Date();

async function loadCalendar() {
  try {
    calendarData = await Api.getCalendar();
  } catch (e) {
    calendarData = {};
  }
  renderCalendarMonth();
}

function renderCalendarMonth() {
  const grid = document.getElementById("calGrid");
  const label = document.getElementById("calLabel");
  const year = calViewDate.getFullYear();
  const month = calViewDate.getMonth();
  label.textContent = `${year}年${month + 1}月`;

  const firstDay = new Date(year, month, 1);
  const startWeekday = firstDay.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const monthValues = [];
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    if (calendarData[key]) monthValues.push(calendarData[key].profit_loss);
  }
  const maxAbs = Math.max(1, ...monthValues.map(v => Math.abs(v)));

  const weekdayLabels = ["日", "月", "火", "水", "木", "金", "土"];
  let html = weekdayLabels.map(w => `<div class="cal-weekday">${w}</div>`).join("");
  for (let i = 0; i < startWeekday; i++) html += `<div class="cal-cell empty"></div>`;

  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const entry = calendarData[key];
    if (!entry) {
      html += `<div class="cal-cell no-trade">${d}</div>`;
    } else {
      const intensity = Math.min(1, Math.abs(entry.profit_loss) / maxAbs);
      const alpha = 0.25 + intensity * 0.6;
      const color = entry.profit_loss >= 0 ? `rgba(47,191,113,${alpha})` : `rgba(229,72,77,${alpha})`;
      const cls = entry.profit_loss >= 0 ? "profit" : "loss";
      html += `<div class="cal-cell ${cls}" style="background:${color}" data-date="${key}">${d}</div>`;
    }
  }

  grid.innerHTML = html;
  grid.querySelectorAll(".cal-cell[data-date]").forEach(cell => {
    cell.addEventListener("click", () => showCalDayDetail(cell.dataset.date));
  });
}

function showCalDayDetail(dateKey) {
  const entry = calendarData[dateKey];
  const detail = document.getElementById("calDayDetail");
  if (!entry) { detail.hidden = true; return; }
  const emotions = entry.emotions.length ? entry.emotions.join(", ") : "記録なし";
  detail.hidden = false;
  detail.innerHTML = `
    <div class="reason-block"><span class="k">${dateKey}</span>
    損益: ${entry.profit_loss > 0 ? "+" : ""}${entry.profit_loss} ・ ${entry.trade_count}件<br>
    感情: ${escapeHtml(emotions)}</div>
  `;
}

document.getElementById("calPrev").addEventListener("click", () => {
  calViewDate.setMonth(calViewDate.getMonth() - 1);
  renderCalendarMonth();
});
document.getElementById("calNext").addEventListener("click", () => {
  calViewDate.setMonth(calViewDate.getMonth() + 1);
  renderCalendarMonth();
});

document.getElementById("milestoneBtn").addEventListener("click", async () => {
  const btn = document.getElementById("milestoneBtn");
  const result = document.getElementById("milestoneResult");
  btn.disabled = true;
  btn.textContent = "分析中...";
  try {
    const data = await Api.getMilestoneAnalysis();
    const a = data.analysis || {};
    const line = (title, key) => a[key] ? `<div class="reason-block"><span class="k">${title}</span>${escapeHtml(a[key])}</div>` : "";
    result.hidden = false;
    result.innerHTML = [
      line("勝っている条件", "winning_conditions"),
      line("負けている条件", "losing_conditions"),
      line("共通する勝ちパターン", "common_winning_patterns"),
      line("共通する負けパターン", "common_losing_patterns"),
      line("削除すべきルール", "rules_to_remove"),
      line("追加すべきルール", "rules_to_add"),
      line("勝率より期待値が高い条件", "high_expectancy_low_winrate"),
      line("勝率は高いが期待値が低い条件", "high_winrate_low_expectancy"),
      line("最も改善効果が高い課題", "top_improvement_priority"),
      line("信頼性についてのコメント", "reliability_note"),
    ].join("");
  } catch (e) {
    result.hidden = false;
    result.innerHTML = `<div class="reason-block">${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "節目分析を実行(20件以上で利用可)";
  }
});

// ---------- 仮説検証 ----------
let hypothesisSelectedTags = new Set();

async function renderHypothesisTagPicker() {
  const container = document.getElementById("hypothesisTagsPicker");
  const library = await Api.getRuleTagLibrary().catch(() => ({}));
  const categories = Object.keys(library);
  if (!categories.length) {
    container.innerHTML = `<span class="hint">タグライブラリが空です</span>`;
    return;
  }
  container.innerHTML = categories.map(cat => `
    <div>
      <div class="tag-cat-label">${escapeHtml(cat)}</div>
      <div class="tag-chips">
        ${library[cat].map(t => `
          <button type="button" class="tag-chip ${hypothesisSelectedTags.has(t.name) ? "selected" : ""}" data-tag="${escapeHtml(t.name)}">${escapeHtml(t.name)}</button>
        `).join("")}
      </div>
    </div>
  `).join("");

  container.querySelectorAll(".tag-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const tag = chip.dataset.tag;
      if (hypothesisSelectedTags.has(tag)) hypothesisSelectedTags.delete(tag);
      else hypothesisSelectedTags.add(tag);
      chip.classList.toggle("selected");
    });
  });
}

document.getElementById("hypothesisForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!hypothesisSelectedTags.size) { alert("対象タグを1つ以上選んでください"); return; }
  const formData = new FormData(e.target);
  const payload = {
    name: formData.get("name"),
    notes: formData.get("notes") || null,
    tags: Array.from(hypothesisSelectedTags),
  };
  try {
    await Api.createHypothesis(payload);
    e.target.reset();
    hypothesisSelectedTags = new Set();
    renderHypothesisTagPicker();
    loadHypotheses();
  } catch (err) {
    alert(err.message);
  }
});

async function loadHypotheses() {
  renderHypothesisTagPicker();
  const container = document.getElementById("hypothesisList");
  try {
    const hypotheses = await Api.listHypotheses();
    if (!hypotheses.length) {
      container.innerHTML = `<div class="empty-state">まだ登録された仮説がありません</div>`;
      return;
    }
    container.innerHTML = hypotheses.map(h => {
      const sr = h.verification.since_registration;
      const ref = h.verification.all_time_reference;
      return `
        <div class="list-item">
          <div class="top-row"><span class="pair">${escapeHtml(h.name)}</span>
            <button class="tag-del-btn" data-id="${h.id}">削除</button>
          </div>
          <div class="meta">対象タグ: ${h.tags.map(escapeHtml).join(" / ")}</div>
          <div class="reason-block">
            <span class="k">登録後のみ(検証用) - ${formatDate(h.created_at)}以降</span>
            ${sr.trade_count}件 ・ 勝率 ${fmtPct(sr.win_rate)} ・ 期待値 ${sr.expectancy_pct != null ? sr.expectancy_pct + "%" : "-"}
          </div>
          <div class="reason-block">
            <span class="k">全期間(参考・後付け含む)</span>
            ${ref.trade_count}件 ・ 勝率 ${fmtPct(ref.win_rate)} ・ 期待値 ${ref.expectancy_pct != null ? ref.expectancy_pct + "%" : "-"}
          </div>
        </div>
      `;
    }).join("");
    container.querySelectorAll(".tag-del-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("この仮説を削除しますか?")) return;
        await Api.deleteHypothesis(btn.dataset.id);
        loadHypotheses();
      });
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-state">仮説一覧を取得できませんでした</div>`;
  }
}

document.getElementById("clearDataBtn").addEventListener("click", async () => {
  if (!confirm("すべてのデータ(分析履歴・トレード記録)を削除します。元に戻せません。よろしいですか?")) return;
  try {
    await Api.clearAllData();
    loadStatistics();
    loadTrades();
    loadAnalysisHistory();
    alert("全データを削除しました");
  } catch (e) {
    alert(e.message);
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
