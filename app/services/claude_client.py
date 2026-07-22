"""
Gemini API とのやり取りを担当するクライアント。
チャート画像分析・改善提案生成の両方で使い回す。
(元はClaude APIを使用していたが、無料枠のあるGemini APIに変更)
"""
import json
import google.generativeai as genai
from app.core.config import settings

_configured = False


def _ensure_configured():
    global _configured
    if not _configured:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _configured = True


MODEL_NAME = "gemini-flash-latest"

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
    """チャート画像をGeminiに送り、構造化された分析結果を取得する"""
    _ensure_configured()
    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=CHART_ANALYSIS_SYSTEM_PROMPT,
    )

    response = model.generate_content(
        [
            {"mime_type": media_type, "data": image_bytes},
            "このチャート画像を分析してください。",
        ],
        generation_config={"max_output_tokens": 2000},
    )

    raw_text = response.text
    parsed = _safe_json_parse(raw_text)
    parsed["_raw_response"] = raw_text
    return parsed


def generate_improvement_suggestions(stats_summary: dict) -> dict:
    """統計データをもとに改善提案をGeminiに生成させる"""
    _ensure_configured()
    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=IMPROVEMENT_SYSTEM_PROMPT,
    )

    response = model.generate_content(
        "以下は過去のトレード統計データです。JSON形式で改善提案をしてください。\n\n"
        + json.dumps(stats_summary, ensure_ascii=False, default=str),
        generation_config={"max_output_tokens": 2000},
    )

    return _safe_json_parse(response.text)


def _safe_json_parse(raw_text: str) -> dict:
    """Geminiのレスポンスからjsonを安全に取り出す(コードブロック等が混ざっても対応)"""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "JSON解析に失敗しました", "raw": raw_text}

TRADE_HISTORY_SYSTEM_PROMPT = """\
あなたは証券会社の約定履歴画面を読み取る専門家です。GMOクリック証券などの取引アプリの
「約定履歴」画面のスクリーンショットが渡されます。表の各行を読み取り、
必ず以下のJSON配列形式のみで回答してください。前置きや説明文は不要です。

[
  {
    "row_type": "open または close (新規注文の行はopen、決済注文の行はclose)",
    "currency_pair": "銘柄名(例: USDJPY, 銀スポットなど画面に表示されている名称そのまま)",
    "side": "buy または sell (買/売)",
    "price": 約定価格(数値),
    "quantity": 約定数量(数値),
    "datetime": "約定日時。ISO8601形式(YYYY-MM-DDTHH:MM:SS)に変換。年が画面になければ今年と仮定",
    "profit_loss": "受渡金額・損益(数値)。決済行のみ、読み取れなければnull"
  }
]

画面に表示されている行はすべて含めてください。読み取れない項目はnullにしてください。
"""
def extract_trade_rows(image_bytes: bytes, media_type: str = "image/png") -> list:
    """約定履歴画像をGeminiに送り、行データのリストを取得する"""
    _ensure_configured()
    from datetime import date
    current_year = date.today().year

    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=TRADE_HISTORY_SYSTEM_PROMPT,
    )

    response = model.generate_content(
        [
            {"mime_type": media_type, "data": image_bytes},
            f"この約定履歴の画像を読み取ってください。今年は{current_year}年です。画面に年が表示されていない日付はすべて{current_year}年として扱ってください。",
        ],
        generation_config={"max_output_tokens": 6000},
    )

    raw_text = response.text.strip()
    json_str = _extract_json_array(raw_text)
    try:
        result = json.loads(json_str)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        raise RuntimeError(f"AI応答の解析に失敗しました。応答内容: {raw_text[:400]}")


def _extract_json_array(text: str) -> str:
    """コードブロックや前置き文が混ざっていても、JSON配列部分だけを取り出す"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text
