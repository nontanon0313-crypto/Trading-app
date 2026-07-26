"""
Gemini API とのやり取りを担当するクライアント。
チャート画像分析・改善提案生成・トレードレビュー・節目分析で使い回す。
(元はClaude APIを使用していたが、無料枠のあるGemini APIに変更)

無料枠のクォータ(利用上限)は使い過ぎると一時的に止まることがあるため、
メインモデルが上限に達した場合は、別枠のクォータを持つ軽量モデルに
自動で切り替えるフォールバック機構を持たせている。
"""
import json
import time
import google.generativeai as genai
from app.core.config import settings

_configured = False


def _ensure_configured():
    global _configured
    if not _configured:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _configured = True


# メインモデルと、クォータ超過時のフォールバック先
# Flash-Lite系は無料枠の1日上限が大きい(500回)ため、こちらを主力にする
MODEL_NAME = "gemini-3.5-flash-lite"
FALLBACK_MODEL_NAME = "gemini-3.1-flash-lite"


def _generate(system_instruction: str, contents, max_output_tokens: int) -> str:
    """Geminiにリクエストを送る。クォータ超過(429)時は自動でフォールバックモデルに切り替える"""
    _ensure_configured()
    last_error = None

    for model_name in (MODEL_NAME, FALLBACK_MODEL_NAME):
        try:
            model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
            response = model.generate_content(
                contents,
                generation_config={"max_output_tokens": max_output_tokens},
            )
            return response.text
        except Exception as e:
            last_error = e
            error_text = str(e)
            is_quota_error = "429" in error_text or "quota" in error_text.lower() or "RESOURCE_EXHAUSTED" in error_text
            if is_quota_error and model_name == MODEL_NAME:
                # メインモデルの無料枠上限。別枠のフォールバックモデルで再試行する
                time.sleep(1)
                continue
            raise

    raise last_error


CHART_ANALYSIS_SYSTEM_PROMPT_HEADER = """\
あなたはFXチャート分析の専門家です。1〜3枚のTradingViewチャート画像が渡されます。
それぞれの画像には、どの時間足かのラベル(例: 4時間足・15分足・1分足)が付いています。
複数枚渡された場合は、上位足で大きな流れを把握し、下位足でエントリータイミングを
検討するというマルチタイムフレーム分析を行ってください。1枚しか無い場合は、
その時間足の範囲内で分析し、上位足に関する項目は「画像が無いため判断不可」としてください。

分析方針:
このチャート分析の目的は、特定の理論が正しいことを証明することではなく、
どのような条件の組み合わせが長期的に期待値の高いトレードになるかを、後から
実際のトレード結果と照合して統計的に検証するためのデータを集めることです。
そのため、以下のルールタグそれぞれについて、判定可能な範囲で必ず評価してください。
「条件が弱いから省略する」「自信が無いので判定しない」という対応はせず、
判断が難しい場合は根拠欄に「推定」であることを明示した上で確信度を下げて出力してください。

このツールはエントリー可否を自動判定するものではありません。断定的な「入るべき/待つべき」
という結論ではなく、条件分岐を含んだ「シナリオ予測」として出力してください
(例:「レジスタンス付近で反発した場合は下落継続、上抜けした場合は上昇加速」のように)。

評価対象のルールタグ一覧:
{tag_list}

各タグについて、以下を出力してください。
- judgment: "yes" | "no" (該当する時間足の画像からその条件が該当するか)
- confidence: 0-100の整数(確信度)
- reason: 判定根拠
- higher_tf_alignment: 上位時間足との整合性についてのコメント(上位足の画像が無ければ「画像が無いため判断不可」)
- direction_impact: "buy" | "sell" | "neutral" (この条件が示す方向性)

また、タグ同士で判定が一致している点(agreement_points)と、矛盾している点(conflict_points)も出力してください。

必ず以下のJSON形式のみで回答してください。前置きや説明文は不要です。

{{
  "currency_pair": "通貨ペア(判別できなければnull)",
  "direction": "long" | "short" | "skip",
  "entry_price": 数値 または null,
  "stop_loss": 数値 または null,
  "take_profit": 数値 または null,
  "risk_reward": 数値 または null,
  "trend": "トレンド方向の説明(複数時間足がある場合はそれぞれ言及)",
  "support_resistance": "サポート・レジスタンスの分析",
  "dow_theory": "ダウ理論に基づく判断",
  "candle_pattern": "ローソク足パターンの分析",
  "moving_average": "移動平均線の状況",
  "rsi_macd": "RSI・MACD等インジケータの分析(表示されていなければ「非表示」)",
  "volatility": "ボラティリティの評価",
  "entry_reason": "このシナリオが有力だと考える根拠(見送りの場合はnull)",
  "skip_reason": "見送るべき理由(見送りでない場合はnull)",
  "scenario_forecast": [
    {{"condition": "分岐条件(例: レジスタンス上抜けした場合)", "expected_move": "予想される値動き", "target_level": "目安となる価格帯(不明ならnull)", "confidence": 0-100の整数}}
  ],
  "tag_evaluations": [
    {{"tag": "タグ名", "judgment": "yes", "confidence": 70, "reason": "...", "higher_tf_alignment": "...", "direction_impact": "buy"}}
  ],
  "agreement_points": "タグ同士の一致点",
  "conflict_points": "タグ同士の矛盾点"
}}
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


def extract_trade_rows(image_bytes: bytes, media_type: str = "image/png") -> list:
    """約定履歴画像をGeminiに送り、行データのリストを取得する"""
    from datetime import date
    current_year = date.today().year

    raw_text = _generate(
        TRADE_HISTORY_SYSTEM_PROMPT,
        [
            {"mime_type": media_type, "data": image_bytes},
            f"この約定履歴の画像を読み取ってください。今年は{current_year}年です。画面に年が表示されていない日付はすべて{current_year}年として扱ってください。",
        ],
        max_output_tokens=6000,
    ).strip()

    json_str = _extract_json_array(raw_text)
    try:
        result = json.loads(json_str)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        raise RuntimeError(f"AI応答の解析に失敗しました。応答内容: {raw_text[:400]}")


def _extract_json_array(text: str) -> str:
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


def analyze_chart_image(images: list, rule_tags: list = None) -> dict:
    """複数時間足のチャート画像(最大3枚)をGeminiに送り、構造化された分析結果を取得する。
    images: [{"bytes": ..., "media_type": ..., "timeframe": "4時間足"}, ...]
    """
    rule_tags = rule_tags or []
    tag_list_text = "\n".join(f"- {t}" for t in rule_tags) if rule_tags else "(タグ未登録)"
    system_prompt = CHART_ANALYSIS_SYSTEM_PROMPT_HEADER.format(tag_list=tag_list_text)

    contents = []
    for img in images:
        contents.append(f"――― 以下は {img['timeframe']} のチャートです ―――")
        contents.append({"mime_type": img["media_type"], "data": img["bytes"]})
    contents.append("これらのチャート画像を分析してください。")

    raw_text = _generate(system_prompt, contents, max_output_tokens=8192)
    json_str = _extract_json_object(raw_text.strip())
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        raise RuntimeError(f"AI応答の解析に失敗しました(出力が途中で切れた可能性があります)。応答内容: {raw_text[-500:]}")
    parsed["_raw_response"] = raw_text
    return parsed


def generate_improvement_suggestions(stats_summary: dict) -> dict:
    """統計データをもとに改善提案をGeminiに生成させる"""
    raw_text = _generate(
        IMPROVEMENT_SYSTEM_PROMPT,
        "以下は過去のトレード統計データです。JSON形式で改善提案をしてください。\n\n"
        + json.dumps(stats_summary, ensure_ascii=False, default=str),
        max_output_tokens=2000,
    )
    return _safe_json_parse(raw_text)


def analyze_trade_review(trade_data: dict) -> dict:
    """1トレード分のデータをもとに、5カテゴリの振り返り分析を行う"""
    raw_text = _generate(
        TRADE_REVIEW_SYSTEM_PROMPT,
        "以下のトレードデータを分析してください。\n\n"
        + json.dumps(trade_data, ensure_ascii=False, default=str),
        max_output_tokens=2000,
    )
    return _safe_json_parse(_extract_json_object(raw_text.strip()))


def analyze_milestone(stats: dict, trades_summary: list) -> dict:
    """節目件数(20/50/100件など)ごとの、蓄積データに基づく統計的分析を行う"""
    payload = {"statistics": stats, "trades": trades_summary}
    raw_text = _generate(
        MILESTONE_SYSTEM_PROMPT,
        "以下の統計データと個々のトレード一覧を分析してください。\n\n"
        + json.dumps(payload, ensure_ascii=False, default=str),
        max_output_tokens=3000,
    )
    return _safe_json_parse(_extract_json_object(raw_text.strip()))


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


def _extract_json_object(text: str) -> str:
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text
