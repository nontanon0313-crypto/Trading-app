#!/usr/bin/env python3
"""Dukascopy 1分足(買値・売値)取得ツール。標準ライブラリのみで動作。

使い方:
  python fetch_dukascopy.py check            # 全銘柄を1日分だけ取得し、形式・価格を検証(DBへは書き込まない)
  python fetch_dukascopy.py run              # 全銘柄を取得(中断しても再実行で続きから再開)
  python fetch_dukascopy.py run --start 2019-01-01 --symbols XAGUSD,USDJPY
  python fetch_dukascopy.py status           # 取得済みの範囲・件数・容量を表示
"""
import argparse
import datetime as dt
import lzma
import os
import sqlite3
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://datafeed.dukascopy.com/datafeed"
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "candles.sqlite")

# 銘柄ごとの「想定価格帯」。価格の桁(割る数)を自動判定し、取り違えを防ぐための検証用。
# 上限/下限の比を10未満にしてあるため、桁は必ず1つに定まる。
RANGES = {
    "XAGUSD": (12, 119),    # 銀
    "XAUUSD": (1000, 9999),  # 金
    "USDJPY": (60, 299),
    "EURJPY": (80, 299),
    "GBPJPY": (100, 299),
    "AUDJPY": (50, 150),
    "EURUSD": (0.8, 1.9),
    "GBPUSD": (0.8, 1.9),
}
DEFAULT_START = dt.date(2021, 1, 1)
REC = struct.Struct(">IIIIIf")  # 秒オフセット, 始値, 終値, 安値, 高値, 出来高
DIVISORS = (1, 10, 100, 1000, 10000, 100000, 1000000)


def url(sym, day, side):
    # 月は0始まり(1月=00)
    return f"{BASE}/{sym}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{side}_candles_min_1.bi5"


def http_get(u, retries=5):
    """503/429等のサーバー混雑時は待ち時間を延ばして再試行する。404はデータ無し(空)として扱う。"""
    err = None
    for i in range(retries):
        wait = (5, 15, 30, 60, 90)[i]
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            err = e
            ra = e.headers.get("Retry-After") if e.headers else None
            if ra and ra.isdigit():
                wait = max(wait, min(int(ra), 120))
        except Exception as e:  # noqa
            err = e
        time.sleep(wait)
    raise RuntimeError(f"取得失敗 {u}: {err}")


def decode(raw):
    if not raw:
        return []
    data = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO).decompress(raw)
    if len(data) % REC.size:
        raise ValueError(f"データ長が{REC.size}の倍数ではありません({len(data)})")
    return [REC.unpack_from(data, i) for i in range(0, len(data), REC.size)]


def validate(rows, label):
    last = -1
    for t, o, c, l, h, _v in rows:
        if not (0 <= t < 86400) or t <= last:
            raise ValueError(f"{label}: 時刻が不正です(t={t})")
        if l > min(o, c) or h < max(o, c):
            raise ValueError(f"{label}: 高値/安値の整合性が取れません(t={t})")
        last = t


def fetch_day(sym, day):
    """買値・売値を取得して検証し、時刻で結合した行を返す。データ無しなら空リスト。"""
    bid = decode(http_get(url(sym, day, "BID")))
    ask = decode(http_get(url(sym, day, "ASK")))
    label = f"{sym} {day}"
    validate(bid, label + " BID")
    validate(ask, label + " ASK")
    if not bid or not ask:
        return []
    a = {r[0]: r for r in ask}
    out = []
    for r in bid:
        x = a.get(r[0])
        if x:
            # t, bo, bh, bl, bc, ao, ah, al, ac, 出来高(買値側)
            out.append((r[0], r[1], r[4], r[3], r[2], x[1], x[4], x[3], x[2], float(r[5])))
    return out


def detect_divisor(sym, rows):
    lo, hi = RANGES[sym]
    med = statistics.median(r[4] for r in rows)
    cands = [d for d in DIVISORS if lo <= med / d <= hi]
    if len(cands) != 1:
        raise ValueError(f"{sym}: 価格の桁を一意に判定できません(中央値={med}, 候補={cands})")
    return cands[0]


def day_epoch(day):
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())


def open_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS m1(
      symbol TEXT, ts INTEGER, bo INTEGER, bh INTEGER, bl INTEGER, bc INTEGER,
      ao INTEGER, ah INTEGER, al INTEGER, ac INTEGER, v REAL,
      PRIMARY KEY(symbol, ts)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS days(symbol TEXT, day TEXT, status TEXT, n INTEGER,
      PRIMARY KEY(symbol, day));
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    return con


def get_divisor(con, sym, rows):
    r = con.execute("SELECT v FROM meta WHERE k=?", (f"divisor_{sym}",)).fetchone()
    if r:
        d = int(r[0])
        lo, hi = RANGES[sym]
        med = statistics.median(x[4] for x in rows)
        if not (lo <= med / d <= hi):
            raise ValueError(f"{sym}: 想定価格帯を外れています(中央値={med / d})。処理を中止します")
        return d
    d = detect_divisor(sym, rows)
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (f"divisor_{sym}", str(d)))
    return d


def cmd_check(_args):
    today = dt.datetime.now(dt.timezone.utc).date()
    day = today - dt.timedelta(days=10)
    while day.weekday() != 2:  # 水曜日
        day -= dt.timedelta(days=1)
    print(f"検証日: {day}(水曜日) / 全{len(RANGES)}銘柄")
    ng = 0
    for sym in RANGES:
        try:
            rows = fetch_day(sym, day)
            if not rows:
                raise ValueError("データが空です")
            d = detect_divisor(sym, rows)
            spreads = [(r[8] - r[4]) / d for r in rows]
            print(f"OK {sym}: {len(rows)}本 桁=1/{d} 始値={rows[0][1] / d} "
                  f"平均スプレッド={statistics.mean(spreads):.5f}")
        except Exception as e:  # noqa
            ng += 1
            print(f"NG {sym}: {e}")
    print("検証結果: 全てOK" if ng == 0 else f"検証結果: {ng}銘柄でNG(上記を確認してください)")
    return 1 if ng else 0


def target_days(start, end, done):
    d = start
    while d <= end:
        if d.weekday() != 5 and d.isoformat() not in done:  # 土曜は市場休場
            yield d
        d += dt.timedelta(days=1)


def safe_fetch(sym, day):
    """取得失敗でも全体を止めない。失敗した日は未取得のまま残り、再実行で再取得される。"""
    try:
        return day, fetch_day(sym, day), None
    except Exception as e:  # noqa
        return day, None, str(e)


def cmd_run(args):
    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(RANGES)
    for s in syms:
        if s not in RANGES:
            print(f"未対応の銘柄です: {s}")
            return 1
    start = dt.date.fromisoformat(args.start) if args.start else DEFAULT_START
    today = dt.datetime.now(dt.timezone.utc).date()
    end = today - dt.timedelta(days=2)
    con = open_db()
    total_failed = 0
    for sym in syms:
        done = {r[0] for r in con.execute("SELECT day FROM days WHERE symbol=?", (sym,))}
        todo = list(target_days(start, end, done))
        print(f"[{sym}] 未取得 {len(todo)}日", flush=True)
        t0 = time.time()
        n_ok = n_fail = 0
        first_err = None
        step = args.workers * 5
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for i in range(0, len(todo), step):
                chunk = todo[i:i + step]
                results = list(ex.map(lambda d: safe_fetch(sym, d), chunk))
                chunk_fail = 0
                for day, rows, err in results:
                    if err:
                        chunk_fail += 1
                        first_err = first_err or err
                        continue
                    if rows:
                        get_divisor(con, sym, rows)  # 想定価格帯を外れたら例外で停止
                        base = day_epoch(day)
                        con.executemany(
                            "INSERT OR REPLACE INTO m1 VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            [(sym, base + r[0], *r[1:]) for r in rows])
                        con.execute("INSERT OR REPLACE INTO days VALUES(?,?,?,?)",
                                    (sym, day.isoformat(), "ok", len(rows)))
                        n_ok += 1
                    elif (today - day).days > 7:
                        con.execute("INSERT OR REPLACE INTO days VALUES(?,?,?,?)",
                                    (sym, day.isoformat(), "empty", 0))
                con.commit()
                n_fail += chunk_fail
                done_n = min(i + len(chunk), len(todo))
                print(f"  {sym} {done_n}/{len(todo)}日 成功{n_ok} 失敗{n_fail} "
                      f"({time.time() - t0:.0f}秒)", flush=True)
                if chunk_fail > len(chunk) // 2:
                    print("  サーバーが混雑しているようです。120秒待ってから続けます", flush=True)
                    time.sleep(120)
        total_failed += n_fail
        print(f"[{sym}] 終了: 取得 {n_ok}日 / 失敗 {n_fail}日", flush=True)
        if first_err:
            print(f"  失敗の例: {first_err}", flush=True)
    if total_failed:
        print(f"失敗が{total_failed}日あります。再実行すると失敗した日だけ再取得します")
        return 2
    return 0


def cmd_status(_args):
    if not os.path.exists(DB_PATH):
        print("まだデータがありません")
        return 0
    con = open_db()
    print(f"DB容量: {os.path.getsize(DB_PATH) / 1024 / 1024:.1f}MB")
    for sym, n, a, b in con.execute("SELECT symbol,COUNT(*),MIN(ts),MAX(ts) FROM m1 GROUP BY symbol"):
        f = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")  # noqa
        ok = con.execute("SELECT COUNT(*) FROM days WHERE symbol=? AND status='ok'", (sym,)).fetchone()[0]
        print(f"{sym}: {n:,}本 {f(a)}〜{f(b)} 取得日数={ok}")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--start")
    r.add_argument("--symbols")
    r.add_argument("--workers", type=int, default=2)
    sub.add_parser("status")
    a = p.parse_args()
    sys.exit({"check": cmd_check, "run": cmd_run, "status": cmd_status}[a.cmd](a))


if __name__ == "__main__":
    main()
