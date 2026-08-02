// バックエンドAPIのベースURL
// Renderにデプロイしたバックエンドのアドレスに置き換えてください
const API_BASE = "https://trading-app-5c7s.onrender.com";

const Api = {
  async healthCheck() {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error("health check failed");
    return res.json();
  },

  async analyzeChart(slots) {
    // slots: [{file, timeframe}, ...] (fileがあるものだけ送る)
    const formData = new FormData();
    slots.filter(s => s.file).forEach(s => {
      formData.append("files", s.file);
      formData.append("timeframes", s.timeframe);
    });
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 130000);
    let res;
    try {
      res = await fetch(`${API_BASE}/api/chart-analysis/`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
    } catch (e) {
      if (e.name === "AbortError") throw new Error("応答がありませんでした(タイムアウト)。画像の枚数を減らすか、時間をおいて再度お試しください。");
      throw e;
    } finally {
      clearTimeout(timeoutId);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "分析に失敗しました");
    }
    return res.json();
  },

  async listAnalyses() {
    const res = await fetch(`${API_BASE}/api/chart-analysis/?limit=20`);
    if (!res.ok) throw new Error("履歴の取得に失敗しました");
    return res.json();
  },

  async createTrade(payload) {
    const res = await fetch(`${API_BASE}/api/trades/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "記録の保存に失敗しました");
    }
    return res.json();
  },

  async previewTradesFromImage(file) {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${API_BASE}/api/trades/from-image/preview`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "画像からの読み取りに失敗しました");
    }
    return res.json();
  },

  async confirmTradesFromImage(items) {
    const res = await fetch(`${API_BASE}/api/trades/from-image/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "取り込みの確定に失敗しました");
    }
    return res.json();
  },

  async autoLinkAnalysis() {
    const res = await fetch(`${API_BASE}/api/trades/auto-link-analysis`, { method: "POST" });
    if (!res.ok) throw new Error("自動紐付けに失敗しました");
    return res.json();
  },

  async getCurrencyPairs() {
    const res = await fetch(`${API_BASE}/api/trades/currency-pairs`);
    if (!res.ok) return [];
    return res.json();
  },

  async getRuleTagLibrary(purpose = "entry") {
    const res = await fetch(`${API_BASE}/api/rule-tags/?purpose=${purpose}`);
    if (!res.ok) return {};
    return res.json();
  },

  async addRuleTagToLibrary(category, name, purpose = "entry") {
    const res = await fetch(`${API_BASE}/api/rule-tags/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, name, purpose }),
    });
    if (!res.ok) throw new Error("タグの追加に失敗しました");
    return res.json();
  },

  async getLeverages() {
    const res = await fetch(`${API_BASE}/api/leverages/`);
    if (!res.ok) return { default_leverage: null, instruments: [] };
    return res.json();
  },

  async upsertLeverage(currency_pair, leverage) {
    const res = await fetch(`${API_BASE}/api/leverages/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ currency_pair, leverage }),
    });
    if (!res.ok) throw new Error("レバレッジの登録に失敗しました");
    return res.json();
  },

  async deleteLeverage(id) {
    const res = await fetch(`${API_BASE}/api/leverages/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error("削除に失敗しました");
    return res.json();
  },

  async getRuleTags() {
    const res = await fetch(`${API_BASE}/api/trades/rule-tags`);
    if (!res.ok) return [];
    return res.json();
  },

  async getTrade(tradeId) {
    const res = await fetch(`${API_BASE}/api/trades/${tradeId}`);
    if (!res.ok) throw new Error("トレード情報の取得に失敗しました");
    return res.json();
  },

  async deleteTrade(tradeId) {
    const res = await fetch(`${API_BASE}/api/trades/${tradeId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("削除に失敗しました");
    return res.json();
  },

  async updateTradeInfo(tradeId, payload) {
    const res = await fetch(`${API_BASE}/api/trades/${tradeId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "基本情報の保存に失敗しました");
    }
    return res.json();
  },

  async updateTradeJournal(tradeId, payload) {
    const res = await fetch(`${API_BASE}/api/trades/${tradeId}/journal`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "日記の保存に失敗しました");
    }
    return res.json();
  },

  async listTrades() {
    const res = await fetch(`${API_BASE}/api/trades/?limit=1000`);
    if (!res.ok) throw new Error("記録一覧の取得に失敗しました");
    return res.json();
  },

  async getStatistics() {
    const res = await fetch(`${API_BASE}/api/statistics/`);
    if (!res.ok) throw new Error("統計の取得に失敗しました");
    return res.json();
  },

  async getCalendar() {
    const res = await fetch(`${API_BASE}/api/statistics/calendar`);
    if (!res.ok) throw new Error("カレンダーデータの取得に失敗しました");
    return res.json();
  },

  async getImprovement() {
    const res = await fetch(`${API_BASE}/api/improvement/`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "改善提案の取得に失敗しました");
    }
    return res.json();
  },

  async clearAllData() {
    const res = await fetch(`${API_BASE}/api/admin/clear-data`, { method: "DELETE" });
    if (!res.ok) throw new Error("データの削除に失敗しました");
    return res.json();
  },

  async linkAnalysis(tradeId, analysisId) {
    const res = await fetch(`${API_BASE}/api/trades/${tradeId}/link-analysis`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analysis_id: analysisId }),
    });
    if (!res.ok) throw new Error("紐付けに失敗しました");
    return res.json();
  },

  async getLinkedAnalysis(tradeId) {
    const res = await fetch(`${API_BASE}/api/trades/${tradeId}/linked-analysis`);
    if (!res.ok) throw new Error("紐付け情報の取得に失敗しました");
    return res.json();
  },

  async reviewTrade(tradeId) {
    const res = await fetch(`${API_BASE}/api/trades/${tradeId}/review`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "AIレビューに失敗しました");
    }
    return res.json();
  },

  async getMilestoneAnalysis() {
    const res = await fetch(`${API_BASE}/api/improvement/milestone`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "節目分析の取得に失敗しました");
    }
    return res.json();
  },

  async listHypotheses() {
    const res = await fetch(`${API_BASE}/api/hypotheses/`);
    if (!res.ok) return [];
    return res.json();
  },

  async createHypothesis(payload) {
    const res = await fetch(`${API_BASE}/api/hypotheses/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "仮説の登録に失敗しました");
    }
    return res.json();
  },

  async deleteHypothesis(id) {
    const res = await fetch(`${API_BASE}/api/hypotheses/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error("仮説の削除に失敗しました");
    return res.json();
  },
};
