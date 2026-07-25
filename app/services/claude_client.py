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


# 無料枠のあるモデル(画像入力に対応)
MODEL_NAME = "gemini-2.0-flash"

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
        # 解析に失敗した場合、AIの生レスポンスを添えてエラーとして通知する(原因調査用)
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
        # パース失敗時は生データを添えてエラーを示す
        return {"error": "JSON解析に失敗しました", "raw": raw_text}


TRADE_REVIEW_SYSTEM_PROMPT = """\
あなたはFXトレードの検証コーチです。1つのトレードのデータ(価格・損益・
エントリー前後の日記、ルールタグ、事前記録か後付けかの情報、紐付けられている場合は
チャート分析結果)が渡されます。

厳守事項:
- is_precommitted が false の場合、エントリー理由やシナリオは結果を見た後に書かれた可能性があるため、その旨を踏まえて評価すること(根拠が本当に妥当だったか、結果を知っているために甘く/厳しく評価していないか、意識すること)。
- 「利益が出たから根拠は正しかった」のような結果からの逆算だけで根拠の妥当性を判断しないこと。根拠そのものの論理性・チャート状況との整合性で評価すること。

以下の観点で分析し、必ず以下のJSON形式のみで回答してください。
データが無い項目は「情報不足のため判断不可」としてください。

{
  "entry_analysis": {
    "reason_sufficient": "根拠は十分だったか",
    "reason_conflict": "根拠同士に矛盾はないか",
    "entry_position": "エントリー位置は適切か",
    "timing": "遅すぎる・早すぎるエントリーではないか"
  },
  "risk_analysis": {
    "stop_loss_position": "損切り位置は適切か",
    "risk_reward": "リスクリワードは十分か",
    "excess_risk": "不必要にリスクを取っていないか"
  },
  "exit_analysis": {
    "take_profit_position": "利確位置の評価",
    "stop_loss_result": "損切り位置の評価(結果を踏まえて)",
    "breakeven_exit": "建値撤退の妥当性(該当する場合)"
  },
  "psychology_analysis": {
    "emotion_impact": "感情が判断へ影響した可能性",
    "rule_violation": "ルール違反の有無",
    "fear_greed_impact": "焦り・欲・恐怖の影響"
  },
  "chart_analysis": {
    "trend_alignment": "エントリーはトレンド/レンジの状況と整合していたか(チャート分析データが無ければ「情報不足のため判断不可」)",
    "ma_position": "移動平均線との位置関係の評価",
    "support_resistance": "サポート・レジスタンスを踏まえた評価",
    "entry_timing_vs_chart": "チャート上のタイミングとして適切だったか"
  },
  "summary": "総合コメント(2-3文)"
}
"""


def analyze_trade_review(trade_data: dict) -> dict:
    """1トレード分のデータをもとに、5カテゴリの振り返り分析を行う"""
    _ensure_configured()
    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=TRADE_REVIEW_SYSTEM_PROMPT,
    )

    response = model.generate_content(
        "以下のトレードデータを分析してください。\n\n"
        + json.dumps(trade_data, ensure_ascii=False, default=str),
        generation_config={"max_output_tokens": 2000},
    )

    return _safe_json_parse(_extract_json_object(response.text.strip()))


MILESTONE_SYSTEM_PROMPT = """\
あなたはFXトレードの統計アナリストです。蓄積されたトレードデータ(統計値と
個々のトレード一覧、各トレードのルールタグ・件数・期待値・事前記録か後付けかの情報)が
渡されます。**必ずデータに基づいて**(推測ではなく)分析してください。

厳守事項:
- 件数が少ない条件について「傾向がある」と述べる場合は、その根拠となる件数と期待値を必ず明記すること。件数が少なく偶然の可能性が高い場合はその旨を明確に述べること。何件あれば十分かの判断はあなた自身が行うこと。
- is_precommitted が false(結果を知った後に記録された可能性がある)トレードの entry_reason 等は、後付けの理由付けである可能性を考慮し、確度の低い情報として扱うこと。is_precommitted が true のトレードの情報をより重視すること。
- 「価格が上がったから上目線が正しかった」のような、結果から逆算しただけの単純な結果論を述べないこと。根拠(ルールタグ・チャート状況)と結果の関係を、複数トレードにまたがる再現性で判断すること。
- ユーザーは自己資金でトレードしています。「サンプル数を増やすためにトレード回数を増やす」という趣旨の提案は絶対にしないこと。改善案は既存データの中で条件を絞り込む方向で提案すること。
- 勝率が高くても期待値が低い条件、勝率が低くても期待値が高い条件を区別して指摘すること。

必ず以下のJSON形式のみで回答してください。十分なデータが無い項目は
「データ不足のため判断不可」としてください。

{
  "winning_conditions": "勝っている条件(該当件数・期待値を明記)",
  "losing_conditions": "負けている条件(該当件数・期待値を明記)",
  "common_winning_patterns": "複数トレードで再現性のある勝ちパターン",
  "common_losing_patterns": "複数トレードで再現性のある負けパターン",
  "rules_to_remove": "削除すべきルール(根拠付き)",
  "rules_to_add": "追加すべきルール(根拠付き)",
  "high_expectancy_low_winrate": "勝率より期待値が高い条件",
  "high_winrate_low_expectancy": "勝率は高いが期待値が低い条件",
  "top_improvement_priority": "最も改善効果が高い課題",
  "reliability_note": "この分析全体の信頼性についての率直なコメント(件数の少なさ・後付け記録の割合などを踏まえて)"
}
"""


def analyze_milestone(stats: dict, trades_summary: list) -> dict:
    """節目件数(20/50/100件など)ごとの、蓄積データに基づく統計的分析を行う"""
    _ensure_configured()
    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=MILESTONE_SYSTEM_PROMPT,
    )

    payload = {"statistics": stats, "trades": trades_summary}
    response = model.generate_content(
        "以下の統計データと個々のトレード一覧を分析してください。\n\n"
        + json.dumps(payload, ensure_ascii=False, default=str),
        generation_config={"max_output_tokens": 3000},
    )

    return _safe_json_parse(_extract_json_object(response.text.strip()))


def _extract_json_object(text: str) -> str:
    """コードブロックや前置き文が混ざっていても、JSONオブジェクト部分だけを取り出す"""
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text
