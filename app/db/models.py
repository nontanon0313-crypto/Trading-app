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

    trade = relationship("Trade", back_populates="analysis", uselist=False)


class Trade(Base):
    """GMOクリック証券の約定履歴・実トレード結果を保存するテーブル"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_id = Column(Integer, ForeignKey("chart_analyses.id"), nullable=True)
    analysis = relationship("ChartAnalysis", back_populates="trade")

    currency_pair = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    profit_loss = Column(Float, nullable=True)               # 損益
    lot_size = Column(Float, nullable=True)
    holding_time_minutes = Column(Integer, nullable=True)
    entry_datetime = Column(DateTime, nullable=True)
    exit_datetime = Column(DateTime, nullable=True)

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


class ChangeLog(Base):
    """変更履歴・エラー記録テーブル"""
    __tablename__ = "change_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    category = Column(String, nullable=False)   # 例: "error", "improvement", "manual_edit"
    description = Column(Text, nullable=False)
    cause = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
