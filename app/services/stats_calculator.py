"""
トレード統計(勝率・PF・最大DD・各種内訳など)を計算するモジュール
"""
from collections import defaultdict
from typing import List
from app.db.models import Trade


def calculate_statistics(trades: List[Trade]) -> dict:
    """トレード一覧から各種統計指標を算出する"""
    closed_trades = [t for t in trades if t.profit_loss is not None]

    if not closed_trades:
        return _empty_stats()

    wins = [t for t in closed_trades if t.profit_loss > 0]
    losses = [t for t in closed_trades if t.profit_loss <= 0]

    total_profit = sum(t.profit_loss for t in wins)
    total_loss = abs(sum(t.profit_loss for t in losses))

    win_rate = len(wins) / len(closed_trades) * 100
    profit_factor = (total_profit / total_loss) if total_loss > 0 else None
    avg_win = (total_profit / len(wins)) if wins else 0
    avg_loss = (total_loss / len(losses)) if losses else 0
    avg_rr = (avg_win / avg_loss) if avg_loss > 0 else None

    max_drawdown = _calculate_max_drawdown(closed_trades)
    max_losing_streak = _calculate_max_streak(closed_trades, winning=False)
    max_winning_streak = _calculate_max_streak(closed_trades, winning=True)

    by_currency = _group_stats(closed_trades, key=lambda t: t.currency_pair)
    by_hour = _group_stats(
        closed_trades,
        key=lambda t: t.entry_datetime.hour if t.entry_datetime else "unknown",
    )
    by_weekday = _group_stats(
        closed_trades,
        key=lambda t: t.entry_datetime.strftime("%A") if t.entry_datetime else "unknown",
    )
    by_side = _group_stats(
        closed_trades,
        key=lambda t: _side_label(t.side),
    )
    by_entry_reason = _group_stats(
        closed_trades,
        key=lambda t: t.journal_entry_reason or "未入力",
    )
    by_exit_reason = _group_stats(
        closed_trades,
        key=lambda t: t.journal_exit_reason or "未入力",
    )
    by_emotion = _group_stats(
        closed_trades,
        key=lambda t: t.journal_emotion or "未入力",
    )
    by_confidence = _group_stats(
        closed_trades,
        key=lambda t: t.journal_confidence if t.journal_confidence is not None else "未入力",
    )

    avg_holding_minutes = _average_holding_time(closed_trades)
    rule_adherence_rate = _rule_adherence_rate(closed_trades)

    return {
        "total_trades": len(closed_trades),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor else None,
        "average_win": round(avg_win, 2),
        "average_loss": round(avg_loss, 2),
        "average_risk_reward": round(avg_rr, 2) if avg_rr else None,
        "max_drawdown": round(max_drawdown, 2),
        "max_winning_streak": max_winning_streak,
        "max_losing_streak": max_losing_streak,
        "average_holding_minutes": avg_holding_minutes,
        "rule_adherence_rate": rule_adherence_rate,
        "by_currency_pair": by_currency,
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "by_side": by_side,
        "by_entry_reason": by_entry_reason,
        "by_exit_reason": by_exit_reason,
        "by_emotion": by_emotion,
        "by_confidence": by_confidence,
    }


def _side_label(side):
    if side == "buy":
        return "ロング"
    if side == "sell":
        return "ショート"
    return "不明"


def _empty_stats() -> dict:
    return {
        "total_trades": 0,
        "win_rate": None,
        "profit_factor": None,
        "average_win": None,
        "average_loss": None,
        "average_risk_reward": None,
        "max_drawdown": None,
        "max_winning_streak": 0,
        "max_losing_streak": 0,
        "average_holding_minutes": None,
        "rule_adherence_rate": None,
        "by_currency_pair": {},
        "by_hour": {},
        "by_weekday": {},
        "by_side": {},
        "by_entry_reason": {},
        "by_exit_reason": {},
        "by_emotion": {},
        "by_confidence": {},
    }


def _calculate_max_drawdown(trades: List[Trade]) -> float:
    sorted_trades = sorted(
        trades, key=lambda t: t.exit_datetime or t.created_at
    )
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted_trades:
        equity += t.profit_loss
        peak = max(peak, equity)
        drawdown = peak - equity
        max_dd = max(max_dd, drawdown)
    return max_dd


def _calculate_max_streak(trades: List[Trade], winning: bool) -> int:
    sorted_trades = sorted(
        trades, key=lambda t: t.exit_datetime or t.created_at
    )
    max_streak = 0
    current_streak = 0
    for t in sorted_trades:
        is_win = t.profit_loss > 0
        if is_win == winning:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def _average_holding_time(trades: List[Trade]):
    durations = []
    for t in trades:
        if t.holding_time_minutes is not None:
            durations.append(t.holding_time_minutes)
        elif t.entry_datetime and t.exit_datetime:
            delta = (t.exit_datetime - t.entry_datetime).total_seconds() / 60
            if delta >= 0:
                durations.append(delta)
    if not durations:
        return None
    return round(sum(durations) / len(durations), 1)


def _rule_adherence_rate(trades: List[Trade]):
    judged = [t for t in trades if t.journal_followed_rule]
    if not judged:
        return None
    followed = [t for t in judged if t.journal_followed_rule == "はい"]
    return round(len(followed) / len(judged) * 100, 2)


def _group_stats(trades: List[Trade], key) -> dict:
    groups = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)

    result = {}
    for group_key, group_trades in groups.items():
        wins = [t for t in group_trades if t.profit_loss > 0]
        result[str(group_key)] = {
            "trade_count": len(group_trades),
            "win_rate": round(len(wins) / len(group_trades) * 100, 2),
            "total_profit_loss": round(sum(t.profit_loss for t in group_trades), 2),
        }
    return result
