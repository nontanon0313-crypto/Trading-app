// バックエンドAPIのベースURL
// Renderにデプロイしたバックエンドのアドレスに置き換えてください
const API_BASE = "https://trading-app-5c7s.onrender.com";

const Api = {
  async healthCheck() {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error("health check failed");
    return res.json();
  },

  async analyzeChart(file) {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${API_BASE}/api/chart-analysis/`, {
      method: "POST",
      body: formData,
    });
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

  async listTrades() {
    const res = await fetch(`${API_BASE}/api/trades/?limit=50`);
    if (!res.ok) throw new Error("記録一覧の取得に失敗しました");
    return res.json();
  },

  async getStatistics() {
    const res = await fetch(`${API_BASE}/api/statistics/`);
    if (!res.ok) throw new Error("統計の取得に失敗しました");
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
};
