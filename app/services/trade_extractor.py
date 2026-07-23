"""
約定履歴の行データ(新規/決済)を、トレード記録(エントリー+決済のペア)に変換する。
同一通貨ペアごとに時系列(古い順)でFIFOペアリングする。
"""
from collections import defaultdict
from datetime import datetime


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except (ValueError, AttributeError):
        return None


def pair_trade_rows(rows: list) -> list:
    """新規(open)/決済(close)の行をペアリングしてトレードのリストに変換する"""
    open_stacks = defaultdict(list)
    trades = []

    sorted_rows = sorted(rows, key=lambda r: _parse_dt(r.get("datetime")) or datetime.min)

    for row in sorted_rows:
        pair = row.get("currency_pair") or "unknown"
        if row.get("row_type") == "open":
            open_stacks[pair].append(row)
        elif row.get("row_type") == "close":
            if open_stacks[pair]:
                open_row = open_stacks[pair].pop(0)
                trades.append({
                    "currency_pair": pair,
                    "side": open_row.get("side"),
                    "entry_price": open_row.get("price"),
                    "exit_price": row.get("price"),
                    "profit_loss": row.get("profit_loss"),
                    "lot_size": open_row.get("quantity"),
                    "entry_datetime": open_row.get("datetime"),
                    "exit_datetime": row.get("datetime"),
                })
            else:
                trades.append({
                    "currency_pair": pair,
                    "side": None,
                    "entry_price": None,
                    "exit_price": row.get("price"),
                    "profit_loss": row.get("profit_loss"),
                    "lot_size": row.get("quantity"),
                    "entry_datetime": None,
                    "exit_datetime": row.get("datetime"),
                })

    for pair, remaining in open_stacks.items():
        for open_row in remaining:
            trades.append({
                "currency_pair": pair,
                "side": open_row.get("side"),
                "entry_price": open_row.get("price"),
                "exit_price": None,
                "profit_loss": None,
                "lot_size": open_row.get("quantity"),
                "entry_datetime": open_row.get("datetime"),
                "exit_datetime": None,
            })

    return trades
