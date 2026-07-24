"""
統計計算ロジックの単体テスト
"""
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.stats_calculator import calculate_statistics


class DummyTrade:
    """DBに依存せずテストするための簡易トレードオブジェクト"""
    def __init__(self, profit_loss, currency_pair="USDJPY", entry_datetime=None, created_at=None):
        self.profit_loss = profit_loss
        self.currency_pair = currency_pair
        self.entry_datetime = entry_datetime or datetime(2026, 1, 1, 10, 0)
        self.exit_datetime = self.entry_datetime + timedelta(minutes=30)
        self.created_at = created_at or self.entry_datetime


def test_empty_trades_returns_zero_stats():
    stats = calculate_statistics([])
    assert stats["total_trades"] == 0
    assert stats["win_rate"] is None


def test_win_rate_calculation():
    trades = [
        DummyTrade(profit_loss=1000),
        DummyTrade(profit_loss=-500),
        DummyTrade(profit_loss=800),
        DummyTrade(profit_loss=-300),
    ]
    stats = calculate_statistics(trades)
    assert stats["total_trades"] == 4
    assert stats["win_rate"] == 50.0


def test_profit_factor_calculation():
    trades = [
        DummyTrade(profit_loss=1000),
        DummyTrade(profit_loss=-500),
    ]
    stats = calculate_statistics(trades)
    assert stats["profit_factor"] == 2.0


def test_max_drawdown_calculation():
    trades = [
        DummyTrade(profit_loss=1000, entry_datetime=datetime(2026, 1, 1)),
        DummyTrade(profit_loss=-1500, entry_datetime=datetime(2026, 1, 2)),
        DummyTrade(profit_loss=500, entry_datetime=datetime(2026, 1, 3)),
    ]
    stats = calculate_statistics(trades)
    assert stats["max_drawdown"] == 1500


def test_group_by_currency_pair():
    trades = [
        DummyTrade(profit_loss=1000, currency_pair="USDJPY"),
        DummyTrade(profit_loss=-500, currency_pair="EURUSD"),
    ]
    stats = calculate_statistics(trades)
    assert "USDJPY" in stats["by_currency_pair"]
    assert "EURUSD" in stats["by_currency_pair"]
