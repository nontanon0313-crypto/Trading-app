#!/usr/bin/env python3
"""Dukascopyの1時間足(買値・売値)を、月ごとのファイルで取得してDBのh1表に保存する。

1分足は1日1ファイルのため、1銘柄で約1,800回のダウンロードが必要(約9時間)。
1時間足は1か月1ファイルのため、1銘柄で約140回で済む。1時間足・4時間足・日足の検証には、1時間足で足りる。

  python fetch_hourly.py check              # 形式の確認(既存の1分足から作った1時間足と一致するか)。DBへは書き込まない
  python fetch_hourly.py run                # 全銘柄を取得(中断しても再実行で続きから再開)
  python fetch_hourly.py run --symbols GBPJPY,EURJPY --start 2021-01-01
"""
import argparse
import datetime as dt
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import fetch_dukascopy as FD

UTC = dt.timezone.utc


def month_url(sym, year, month, side):
    return f"{FD.BASE}/{sym}/{year}/{month - 1:02d}/{side}_candles_hour_1.bi5"


def month_range(year, month):
    a = int(dt.datetime(year, month, 1, tzinfo=UTC).timestamp())
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    b = int(dt.datetime(ny, nm, 1, tzinfo=UTC).timestamp())
    return a, b


def decode_month(raw, year, month):
    """月のファイルを復号する。時刻は月初からの秒。戻り値: [(月初からの秒, 始値, 終値, 安値, 高値, 出来高)]"""
    rows = FD.decode(raw)
    a, b = month_range(year, month)
    span = b - a
    last = -1
    for t, o, c, l, h, _v in rows:
        if not (0 <= t < span) or t % 3600 != 0 or t <= last:
            raise ValueError(f"{year}-{month:02d}: 時刻が不正です(t={t})")
        if l > min(o, c) or h < max(o, c):
            raise ValueError(f"{year}-{month:02d}: 高値/安値の整合性が取れません(t={t})")
        last = t
    return rows


def fetch_month(sym, year, month):
    """買値・売値を取得して検証し、時刻で結合した行を返す。データ無しなら空リスト。"""
    bid = decode_month(FD.http_get(month_url(sym, year, month, "BID")), year, month)
    ask = decode_month(FD.http_get(month_url(sym, year, month, "ASK")), year, month)
    if not bid or not ask:
        return []
    base = month_range(year, month)[0]
    a = {r[0]: r for r in ask}
    out = []
    for r in bid:
        x = a.get(r[0])
        if x:
            # ts, bo, bh, bl, bc, ao, ah, al, ac, 出来高(買値側)
            out.append((base + r[0], r[1], r[4], r[3], r[2], x[1], x[4], x[3], x[2], float(r[5])))
    return out


def open_db():
    con = FD.open_db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS h1(
      symbol TEXT, ts INTEGER, bo INTEGER, bh INTEGER, bl INTEGER, bc INTEGER,
      ao INTEGER, ah INTEGER, al INTEGER, ac INTEGER, v REAL,
      PRIMARY KEY(symbol, ts)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS h1_months(symbol TEXT, ym TEXT, status TEXT, n INTEGER,
      PRIMARY KEY(symbol, ym));
    """)
    return con


def aggregate_m1(con, sym, year, month):
    """既存の1分足から、同じ月の1時間足を作る(確認用)。戻り値: {時刻: (bo,bh,bl,bc,ao,ah,al,ac)}"""
    a, b = month_range(year, month)
    rows = con.execute("SELECT ts,bo,bh,bl,bc,ao,ah,al,ac FROM m1 WHERE symbol=? AND ts>=? AND ts<? ORDER BY ts",
                       (sym, a, b)).fetchall()
    out = {}
    for ts, bo, bh, bl, bc, ao, ah, al, ac in rows:
        k = ts - ts % 3600
        if k not in out:
            out[k] = [bo, bh, bl, bc, ao, ah, al, ac]
        else:
            v = out[k]
            v[1] = max(v[1], bh)
            v[2] = min(v[2], bl)
            v[3] = bc
            v[5] = max(v[5], ah)
            v[6] = min(v[6], al)
            v[7] = ac
    return out


def cmd_check(_a):
    con = open_db()
    ok = True
    # 1) 形式の確認: 全銘柄の1か月分が、検証と価格帯の判定に通ること
    probe = (2023, 6)
    print(f"[形式] {probe[0]}年{probe[1]}月の1時間足を、全銘柄で取得して検証します")
    for sym in FD.RANGES:
        try:
            rows = fetch_month(sym, *probe)
            if not rows:
                raise ValueError("データが空です")
            d = FD.detect_divisor(sym, rows)
            print(f"OK {sym}: {len(rows)}本 桁=1/{d} 始値={rows[0][1] / d}")
        except Exception as e:  # noqa
            ok = False
            print(f"NG {sym}: {e}")
    # 2) 既存の1分足から作った1時間足と一致するか
    for sym in ("XAGUSD", "USDJPY"):
        has = con.execute("SELECT COUNT(*) FROM m1 WHERE symbol=? AND ts>=? AND ts<?",
                          (sym, *month_range(*probe))).fetchone()[0]
        if not has:
            continue
        try:
            hrows = {r[0]: r[1:9] for r in fetch_month(sym, *probe)}
            agg = aggregate_m1(con, sym, *probe)
        except Exception as e:  # noqa
            ok = False
            print(f"NG {sym}(照合): {e}")
            continue
        common = sorted(set(hrows) & set(agg))
        names = ("買値始値", "買値高値", "買値安値", "買値終値", "売値始値", "売値高値", "売値安値", "売値終値")
        print(f"[照合] {sym}: 1時間足 {len(hrows)}本 / 1分足から作成 {len(agg)}本 / 共通 {len(common)}本")
        if not common:
            ok = False
            print("  共通する時刻がありません(時刻の基準が違う可能性)")
            continue
        for k, nm in enumerate(names):
            eq = sum(1 for t in common if hrows[t][k] == agg[t][k])
            diff = max(abs(hrows[t][k] - agg[t][k]) for t in common)
            print(f"  {nm}: 完全一致 {eq / len(common) * 100:.1f}% / 最大のずれ {diff}")
            if eq / len(common) < 0.99:
                ok = False
    print("\n結果: 問題なし" if ok else "\n結果: 要確認(上のNG・一致率を確認してください)")
    return 0 if ok else 1


def months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def safe_fetch(sym, y, m):
    try:
        return (y, m, fetch_month(sym, y, m), None)
    except Exception as e:  # noqa
        return (y, m, None, str(e))


def cmd_run(a):
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else list(FD.RANGES)
    start = dt.date.fromisoformat(a.start)
    today = dt.datetime.now(UTC).date()
    end = (today.replace(day=1) - dt.timedelta(days=1))  # 前月まで(当月は未完了)
    con = open_db()
    failed = 0
    for sym in syms:
        if sym not in FD.RANGES:
            print(f"未対応の銘柄です: {sym}")
            return 1
        done = {r[0] for r in con.execute("SELECT ym FROM h1_months WHERE symbol=?", (sym,))}
        todo = [(y, m) for y, m in months(start, end) if f"{y}-{m:02d}" not in done]
        print(f"[{sym}] 未取得 {len(todo)}か月", flush=True)
        t0 = time.time()
        n_ok = n_fail = 0
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for i in range(0, len(todo), a.workers * 3):
                chunk = todo[i:i + a.workers * 3]
                for y, m, rows, err in ex.map(lambda ym: safe_fetch(sym, *ym), chunk):
                    ym = f"{y}-{m:02d}"
                    if err:
                        n_fail += 1
                        print(f"  失敗 {ym}: {err[:120]}", flush=True)
                        continue
                    if rows:
                        FD.get_divisor(con, sym, rows)
                        con.executemany("INSERT OR REPLACE INTO h1 VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                        [(sym, *r) for r in rows])
                        con.execute("INSERT OR REPLACE INTO h1_months VALUES(?,?,?,?)", (sym, ym, "ok", len(rows)))
                        n_ok += 1
                    else:
                        con.execute("INSERT OR REPLACE INTO h1_months VALUES(?,?,?,?)", (sym, ym, "empty", 0))
                con.commit()
                print(f"  {sym} {min(i + len(chunk), len(todo))}/{len(todo)}か月 成功{n_ok} 失敗{n_fail} "
                      f"({time.time() - t0:.0f}秒)", flush=True)
        failed += n_fail
        print(f"[{sym}] 終了: 取得 {n_ok}か月 / 失敗 {n_fail}か月", flush=True)
    return 2 if failed else 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--symbols")
    r.add_argument("--start", default="2021-01-01")
    r.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    sys.exit({"check": cmd_check, "run": cmd_run}[a.cmd](a))


if __name__ == "__main__":
    main()
