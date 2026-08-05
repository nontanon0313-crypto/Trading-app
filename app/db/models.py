"""
DBモデル定義
SQLAlchemyを使ってSQLiteのテーブルを定義する。
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import relationship
from app.db.database import Base


class ChartAnalysis(Base):
    """TradingViewチャート画像の分析結果を保存するテーブル"""
    __tablename__ = "chart_analyses"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    currency_pair = Column(String, nullable=True)          # 通貨ペア
    direction = Column(String, nullable=True)               # ロング/ショート/見送り
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    risk_reward = Column(Float, nullable=True)

    trend = Column(String, nullable=True)                   # トレンド方向
    support_resistance = Column(Text, nullable=True)        # サポレジ情報(JSON文字列)
    dow_theory = Column(Text, nullable=True)                # ダウ理論の判断
    candle_pattern = Column(Text, nullable=True)            # ローソク足パターン
    moving_average = Column(Text, nullable=True)            # 移動平均線の状況
    rsi_macd = Column(Text, nullable=True)                  # RSI/MACD等
    volatility = Column(Text, nullable=True)

    entry_reason = Column(Text, nullable=True)              # エントリー根拠
    skip_reason = Column(Text, nullable=True)               # 見送り理由(該当時)

    raw_ai_response = Column(Text, nullable=True)           # AIの生レスポンス(監査用)

    # ---- ルールタグ別の網羅的評価(統計的検証用) ----
    tag_evaluations = Column(Text, nullable=True)           # JSON配列: 各タグの判定・確信度・根拠等
    tag_agreements = Column(Text, nullable=True)            # タグ同士の一致点
    tag_conflicts = Column(Text, nullable=True)             # タグ同士の矛盾点

    # ---- シナリオ予測・MTF(複数時間足) ----
    scenario_forecast = Column(Text, nullable=True)         # JSON配列: 分岐シナリオ(条件・予想・目標値・確信度)
    timeframes_used = Column(Text, nullable=True)           # JSON配列: 分析に使った時間足のラベル一覧

    trade = relationship("Trade", back_populates="analysis", uselist=False)


class Trade(Base):
    """GMOクリック証券の約定履歴・実トレード結果を保存するテーブル"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_id = Column(Integer, ForeignKey("chart_analyses.id"), nullable=True)
    analysis = relationship("ChartAnalysis", back_populates="trade")

    currency_pair = Column(String, nullable=False)
    side = Column(String, nullable=True)                      # buy(ロング) / sell(ショート)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    profit_loss = Column(Float, nullable=True)               # 損益
    lot_size = Column(Float, nullable=True)
    holding_time_minutes = Column(Integer, nullable=True)
    entry_datetime = Column(DateTime, nullable=True)
    exit_datetime = Column(DateTime, nullable=True)

    # ---- エントリー前の記録 ----
    journal_entry_reason = Column(Text, nullable=True)        # エントリー理由
    journal_scenario = Column(Text, nullable=True)             # 狙ったシナリオ
    journal_planned_take_profit = Column(Float, nullable=True) # 利確目標
    journal_stop_loss_basis = Column(Text, nullable=True)      # 損切り根拠
    journal_confidence = Column(Integer, nullable=True)        # 確信度(1-5)
    journal_anxiety = Column(Text, nullable=True)               # 不安要素
    journal_skip_consideration = Column(Text, nullable=True)   # 見送る理由はあったか
    journal_followed_rule = Column(String, nullable=True)      # ルール通りか(はい/いいえ/一部)
    journal_reversal_sign = Column(String, nullable=True)       # 反発・反転のサインは無かったか("none"/"ignored"/"unsure")
    journal_reversal_sign_note = Column(Text, nullable=True)    # ↑"ignored"の場合の、サインの内容メモ
    journal_emotion = Column(String, nullable=True)            # 感情(焦り/FOMO/冷静 等)
    journal_pre_notes = Column(Text, nullable=True)            # 自由記述(エントリー前)

    # ---- 決済後の記録 ----
    journal_exit_reason = Column(Text, nullable=True)          # 利確/損切り理由
    journal_as_expected = Column(String, nullable=True)        # 想定通りだったか
    journal_improvement = Column(Text, nullable=True)          # 改善点
    journal_post_notes = Column(Text, nullable=True)           # 自由記述(決済後)

    # ---- AIによる毎回のレビュー結果 ----
    ai_review = Column(Text, nullable=True)                    # JSON文字列(5カテゴリ分析)
    ai_review_created_at = Column(DateTime, nullable=True)

    # ---- 事前記録・ルールタグ ----
    journal_pre_committed_at = Column(DateTime, nullable=True)  # エントリー理由等を最初に保存した日時
    journal_rule_tags = Column(Text, nullable=True)             # JSON配列文字列(複合条件タグ)
    journal_exit_reason_tags = Column(Text, nullable=True)      # JSON配列文字列(決済理由タグ)

    verification = relationship("Verification", back_populates="trade", uselist=False)


class Verification(Base):
    """チャート分析結果と実トレード結果の比較・検証結果を保存するテーブル"""
    __tablename__ = "verifications"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=False)
    trade = relationship("Trade", back_populates="verification")

    entry_was_appropriate = Column(String, nullable=True)    # 適切だったか(はい/いいえ/一部)
    stop_loss_was_appropriate = Column(String, nullable=True)
    take_profit_was_appropriate = Column(String, nullable=True)
    skip_was_correct = Column(String, nullable=True)

    working_reasons = Column(Text, nullable=True)            # 機能した根拠
    failing_reasons = Column(Text, nullable=True)            # 失敗した根拠
    notes = Column(Text, nullable=True)


class Hypothesis(Base):
    """仮説(時間帯・方向などタグ以外の切り口)を登録し、登録日以降のデータだけで再現性を検証するためのテーブル。
    タグに基づく仮説は「内訳」画面(エントリールールタグ別)で常時確認できるため、この機能では扱わない。"""
    __tablename__ = "hypotheses"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    name = Column(String, nullable=False)          # 仮説の名前(例: 10時からずっと上がる)
    tags = Column(Text, nullable=False, default="[]")  # 旧仕様の名残(廃止済み、常に空配列を格納)
    notes = Column(Text, nullable=True)             # メモ

    entry_hour_start = Column(Integer, nullable=True)   # 時間帯フィルタ(開始時, 0-23)
    entry_hour_end = Column(Integer, nullable=True)     # 時間帯フィルタ(終了時, 0-23)
    direction = Column(String, nullable=True)           # "buy"(ロングのみ) / "sell"(ショートのみ) / null(指定なし)


class DailyReflection(Base):
    """1日分のチャート画像から、見送った機会・無駄なホールドを振り返るためのテーブル。
    統計・期待値計算には一切使わない、後付けの気づき用の参考記録。"""
    __tablename__ = "daily_reflections"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    reflection_date = Column(String, nullable=False)   # 対象の集計日(YYYY-MM-DD、7:15〜翌7:14基準)
    missed_opportunities = Column(Text, nullable=True)  # 見送った(気づかなかった)機会の分析結果(JSON配列文字列)
    holding_review = Column(Text, nullable=True)        # その日の実トレードの、無駄なホールドについての分析結果(JSON配列文字列)
    raw_ai_response = Column(Text, nullable=True)


class InstrumentLeverage(Base):
    """銘柄(通貨ペア)ごとのレバレッジ設定。未登録の銘柄はデフォルト値を使う。"""
    __tablename__ = "instrument_leverages"

    id = Column(Integer, primary_key=True, index=True)
    currency_pair = Column(String, unique=True, nullable=False)
    leverage = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class RuleTag(Base):
    """事前記録・決済で使うタグのマスタ(カテゴリ別・編集可能)
    purpose: "entry"(エントリー時のルールタグ) または "exit"(決済理由タグ)"""
    __tablename__ = "rule_tags"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False)
    name = Column(String, nullable=False)
    purpose = Column(String, nullable=False, default="entry")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChangeLog(Base):
    """変更履歴・エラー記録テーブル"""
    __tablename__ = "change_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    category = Column(String, nullable=False)   # 例: "error", "improvement", "manual_edit"
    description = Column(Text, nullable=False)
    cause = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
