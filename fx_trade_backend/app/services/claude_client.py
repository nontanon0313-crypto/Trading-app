"""
Claude APIとのやり取りを担当するクライアント。
チャート画像分析・改善提案生成の両方で使い回す。
"""
import base64
import json
from anthropic import Anthropic
from app.core.config import settings

_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY) if settings.ANTHROPIC_API_KEY else None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


CHART_ANALYSIS_SYSTEM_PROMPT = """\
あなたはFXチャート分析の専門家です。送られたTradingViewのチャート画像を分析し、
必ず以下のJSON形式のみで回答してください。前置きや説明文は不要です。

{
  "currency_pair": "通貨ペア(判別できなければnull)",
  "direction": "long" | "short" | "skip",
  "entry_price": 数値 または null,
  "stop_loss": 数値 または null,
  "take_profit": 数値 または null,
  "risk_reward": 数値 または null,
  "trend": "トレンド方向の説明",
  "support_resistance": "サポート・レジスタンスの分析",
  "dow_theory": "ダウ理論に基づく判断",
  "candle_pattern": "ローソク足パターンの分析",
  "moving_average": "移動平均線の状況",
  "rsi_macd": "RSI・MACD等インジケータの分析",
  "volatility": "ボラティリティの評価",
  "entry_reason": "エントリー根拠(見送りの場合はnull)",
  "skip_reason": "見送るべき理由(見送りでない場合はnull)"
}
"""

IMPROVEMENT_SYSTEM_PROMPT = """\
あなたはFXトレードのコーチです。渡された過去のトレード統計データをもとに、
勝率が高いパターン・低いパターン、エントリー/損切り/利確の改善案、
避けるべき相場条件を、必ず以下のJSON形式のみで回答してください。

{
  "winning_patterns": ["..."],
  "losing_patterns": ["..."],
  "entry_improvements": ["..."],
  "stop_loss_improvements": ["..."],
  "take_profit_improvements": ["..."],
  "avoid_conditions": ["..."]
}
"""


def analyze_chart_image(image_bytes: bytes, media_type: str = "image/png") -> dict:
    """チャート画像をClaudeに送り、構造化された分析結果を取得する"""
    client = _get_client()
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=CHART_ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_image,
                        },
                    },
                    {
                        "type": "text",
                        "text": "このチャート画像を分析してください。",
                    },
                ],
            }
        ],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    parsed = _safe_json_parse(raw_text)
    parsed["_raw_response"] = raw_text
    return parsed


def generate_improvement_suggestions(stats_summary: dict) -> dict:
    """統計データをもとに改善提案をClaudeに生成させる"""
    client = _get_client()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=IMPROVEMENT_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "以下は過去のトレード統計データです。JSON形式で改善提案をしてください。\n\n"
                    + json.dumps(stats_summary, ensure_ascii=False, default=str)
                ),
            }
        ],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    return _safe_json_parse(raw_text)


def _safe_json_parse(raw_text: str) -> dict:
    """Claudeのレスポンスからjsonを安全に取り出す(コードブロック等が混ざっても対応)"""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # パース失敗時は生データを添えてエラーを示す
        return {"error": "JSON解析に失敗しました", "raw": raw_text}
