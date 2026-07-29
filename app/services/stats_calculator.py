"""
トレード統計(勝率・PF・期待値・最大DD・各種内訳など)を計算するモジュール

期待値は「証拠金対比リターン(%)・レバレッジ込み」を主指標とする。
ロットは毎回変動するため、金額ベースの平均損益は条件同士の比較に使えないため。
レバレッジは銘柄(通貨ペア)ごとに異なるため、leverage_map(通貨ペア→レバレッジ)を
外部から渡せるようにしている。渡されなければ、環境変数のデフォルト値を使う。
"""
import json as _json
from collections import defaultdict
from typing import List, Optional, Dict
from app.db.models import Trade
from app.core.config import settings


def _leverage_for(t: Trade, leverage_map: Optional[Dict[str, float]]) -> float:
    if leverage_map and t.currency_pair in leverage_map:
        return leverage_map[t.currency_pair]
    return settings.LEVERAGE


def _return_pct(t: Trade, leverage_map: Optional[Dict[str, float]] = None) -> Optional[float]:
    """証拠金に対するリターン率(%)を計算する。
    価格変動率に、銘柄ごとのレバレッジ(未登録ならデフォルト値)を掛けることで、
    ロットサイズに依存せず、実際にフルレバで張った場合の資金効率を反映した値になる。
    符号は実際の損益(profit_loss)の符号に合わせる(side表記の誤りに影響されないため)。"""
    if t.entry_price is None or t.exit_price is None or t.profit_loss is None or t.entry_price == 0:
        return None
    price_move_pct = abs(t.exit_price - t.entry_price) / abs(t.entry_price) * 100
    leverage = _leverage_for(t, leverage_map)
    leveraged_pct = price_move_pct * leverage
    return leveraged_pct if t.profit_loss >= 0 else -leveraged_pct


def calculate_statistics(trades: List[Trade], leverage_map: Optional[Dict[str, float]] = None) -> dict:
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

    # 期待値(金額ベース、参考値。ロットが変動するため条件間の比較には不適切)
    expectancy = sum(t.profit_loss for t in closed_trades) / len(closed_trades)

    # 期待値(証拠金対比%ベース・レバレッジ込み、主指標)
    pct_values = [v for v in (_return_pct(t, leverage_map) for t in closed_trades) if v is not None]
    expectancy_pct = round(sum(pct_values) / len(pct_values), 3) if pct_values else None

    max_drawdown = _calculate_max_drawdown(closed_trades)
    max_losing_streak = _calculate_max_streak(closed_trades, winning=False)
    max_winning_streak = _calculate_max_streak(closed_trades, winning=True)

    by_currency = _group_stats(closed_trades, key=lambda t: t.currency_pair, leverage_map=leverage_map)
    by_hour = _group_stats(
        closed_trades,
        key=lambda t: t.entry_datetime.hour if t.entry_datetime else "unknown",
        leverage_map=leverage_map,
    )
    by_weekday = _group_stats(
        closed_trades,
        key=lambda t: t.entry_datetime.strftime("%A") if t.entry_datetime else "unknown",
        leverage_map=leverage_map,
    )
    by_side = _group_stats(closed_trades, key=lambda t: _side_label(t.side), leverage_map=leverage_map)
    by_entry_reason = _group_stats(closed_trades, key=lambda t: t.journal_entry_reason or "未入力", leverage_map=leverage_map)
    by_exit_reason = _group_stats(closed_trades, key=lambda t: t.journal_exit_reason or "未入力", leverage_map=leverage_map)
    by_emotion = _group_stats(closed_trades, key=lambda t: t.journal_emotion or "未入力", leverage_map=leverage_map)
    by_confidence = _group_stats(
        closed_trades,
        key=lambda t: t.journal_confidence if t.journal_confidence is not None else "未入力",
        leverage_map=leverage_map,
    )
    by_rule_tag = _group_stats_multi(closed_trades, tags_fn=_extract_tags, leverage_map=leverage_map)

    avg_holding_minutes = _average_holding_time(closed_trades)
    rule_adherence_rate = _rule_adherence_rate(closed_trades)
    precommit_rate = _precommit_rate(closed_trades)

    return {
        "total_trades": len(closed_trades),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "expectancy_pct": expectancy_pct,
        "expectancy": round(expectancy, 2),
        "average_win": round(avg_win, 2),
        "average_loss": round(avg_loss, 2),
        "average_risk_reward": round(avg_rr, 2) if avg_rr else None,
        "max_drawdown": round(max_drawdown, 2),
        "max_winning_streak": max_winning_streak,
        "max_losing_streak": max_losing_streak,
        "average_holding_minutes": avg_holding_minutes,
        "rule_adherence_rate": rule_adherence_rate,
        "precommit_rate": precommit_rate,
        "by_currency_pair": by_currency,
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "by_side": by_side,
        "by_entry_reason": by_entry_reason,
        "by_exit_reason": by_exit_reason,
        "by_emotion": by_emotion,
        "by_confidence": by_confidence,
        "by_rule_tag": by_rule_tag,
    }


def _side_label(side):
    if side == "buy":
        return "ロング"
    if side == "sell":
        return "ショート"
    return "不明"


def _extract_tags(t: Trade) -> list:
    if not t.journal_rule_tags:
        return []
    try:
        return _json.loads(t.journal_rule_tags)
    except (ValueError, TypeError):
        return []


def _empty_stats() -> dict:
    return {
        "total_trades": 0,
        "win_rate": None,
        "profit_factor": None,
        "expectancy_pct": None,
        "expectancy": None,
        "average_win": None,
        "average_loss": None,
        "average_risk_reward": None,
        "max_drawdown": None,
        "max_winning_streak": 0,
        "max_losing_streak": 0,
        "average_holding_minutes": None,
        "rule_adherence_rate": None,
        "precommit_rate": None,
        "by_currency_pair": {},
        "by_hour": {},
        "by_weekday": {},
        "by_side": {},
        "by_entry_reason": {},
        "by_exit_reason": {},
        "by_emotion": {},
        "by_confidence": {},
        "by_rule_tag": {},
    }


def _calculate_max_drawdown(trades: List[Trade]) -> float:
    sorted_trades = sorted(trades, key=lambda t: t.exit_datetime or t.created_at)
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
    sorted_trades = sorted(trades, key=lambda t: t.exit_datetime or t.created_at)
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


def _precommit_rate(trades: List[Trade]):
    judged = [t for t in trades if t.journal_pre_committed_at and t.exit_datetime]
    if not judged:
        return None
    precommitted = [t for t in judged if t.journal_pre_committed_at < t.exit_datetime]
    return round(len(precommitted) / len(judged) * 100, 2)


def _group_stats(trades: List[Trade], key, leverage_map: Optional[Dict[str, float]] = None) -> dict:
    groups = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)

    result = {}
    for group_key, group_trades in groups.items():
        wins = [t for t in group_trades if t.profit_loss > 0]
        n = len(group_trades)
        total_pl = sum(t.profit_loss for t in group_trades)
        pct_values = [v for v in (_return_pct(t, leverage_map) for t in group_trades) if v is not None]
        result[str(group_key)] = {
            "trade_count": n,
            "win_rate": round(len(wins) / n * 100, 2),
            "total_profit_loss": round(total_pl, 2),
            "expectancy_pct": round(sum(pct_values) / len(pct_values), 3) if pct_values else None,
            "expectancy": round(total_pl / n, 2),
        }
    return result


def _group_stats_multi(trades: List[Trade], tags_fn, leverage_map: Optional[Dict[str, float]] = None) -> dict:
    """1トレードが複数タグを持つ場合、各タグの集合ごとに集計する(重複所属あり)"""
    groups = defaultdict(list)
    for t in trades:
        for tag in tags_fn(t):
            groups[tag].append(t)

    result = {}
    for tag, group_trades in groups.items():
        wins = [t for t in group_trades if t.profit_loss > 0]
        n = len(group_trades)
        total_pl = sum(t.profit_loss for t in group_trades)
        pct_values = [v for v in (_return_pct(t, leverage_map) for t in group_trades) if v is not None]
        result[tag] = {
            "trade_count": n,
            "win_rate": round(len(wins) / n * 100, 2),
            "total_profit_loss": round(total_pl, 2),
            "expectancy_pct": round(sum(pct_values) / len(pct_values), 3) if pct_values else None,
            "expectancy": round(total_pl / n, 2),
        }
    return result


def calculate_daily_calendar(trades: List[Trade]) -> dict:
    """日付ごとの損益・トレード数・感情をカレンダーヒートマップ用に集計する"""
    closed = [t for t in trades if t.profit_loss is not None]
    daily = defaultdict(lambda: {"profit_loss": 0.0, "trade_count": 0, "emotions": []})

    for t in closed:
        d = t.exit_datetime or t.entry_datetime or t.created_at
        if not d:
            continue
        key = d.strftime("%Y-%m-%d")
        daily[key]["profit_loss"] += t.profit_loss
        daily[key]["trade_count"] += 1
        if t.journal_emotion:
            daily[key]["emotions"].append(t.journal_emotion)

    result = {}
    for date_key, v in daily.items():
        result[date_key] = {
            "profit_loss": round(v["profit_loss"], 2),
            "trade_count": v["trade_count"],
            "emotions": v["emotions"],
        }
    return result
