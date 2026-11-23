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
from concurrent.futures import ThreadPoolExecutor, as_completed

import fetch_dukascopy as FD

UTC = dt.timezone.utc
PROBE = (2023, 6)   # 形式の確認に使う月


def _get(u, tries=3, timeout=45):
    """503や応答待ちの失敗は、待ち時間を延ばして再試行する。404はデータ無し(空)として扱う。"""
    err = None
    for i in range(tries):
        wait = (5, 15, 30)[i]
        try:
            req = FD.urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with FD.urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except FD.urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            err = e
        except Exception as e:  # noqa
            err = e
        time.sleep(wait)
    raise RuntimeError(f"取得失敗 {u}: {err}")


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


def is_idle(r):
    """取引のない時間の足か。r=(時刻, 始値, 終値, 安値, 高値, 出来高)"""
    return r[5] == 0 and r[1] == r[2] == r[3] == r[4]


def fetch_month(sym, year, month, keep_zero=False):
    """買値・売値を取得して検証し、時刻で結合した行を返す。データ無しなら空リスト。
    取引のない時間の足(始値=高値=安値=終値で、出来高が0)は除く。keep_zero=Trueなら残す(確認用)。
    出来高が0でも、値動きのある足は、実際に取引のあった時間なので残す。"""
    bid = decode_month(_get(month_url(sym, year, month, "BID")), year, month)
    ask = decode_month(_get(month_url(sym, year, month, "ASK")), year, month)
    if not bid or not ask:
        return []
    base = month_range(year, month)[0]
    a = {r[0]: r for r in ask}
    out = []
    for r in bid:
        x = a.get(r[0])
        if x and (keep_zero or not is_idle(r)):
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
    """既存の1分足から、同じ月の1時間足を作る(確認用)。戻り値: {時刻: (bo,bh,bl,bc,ao,ah,al,ac)}
    1分足には、取引のない時間にも、値動きのない足(出来高0)が入っている。1時間足側と同じ基準で、
    その時間の全ての足が「値動きなし・出来高0」の時間は除く。"""
    a, b = month_range(year, month)
    rows = con.execute("SELECT ts,bo,bh,bl,bc,ao,ah,al,ac,v FROM m1 WHERE symbol=? AND ts>=? AND ts<? ORDER BY ts",
                       (sym, a, b)).fetchall()
    out = {}
    busy = {}
    for ts, bo, bh, bl, bc, ao, ah, al, ac, v in rows:
        k = ts - ts % 3600
        if bo != bh or bo != bl or bo != bc or v > 0:
            busy[k] = True
        if k not in out:
            out[k] = [bo, bh, bl, bc, ao, ah, al, ac]
        else:
            x = out[k]
            x[1] = max(x[1], bh)
            x[2] = min(x[2], bl)
            x[3] = bc
            x[5] = max(x[5], ah)
            x[6] = min(x[6], al)
            x[7] = ac
    return {k: v for k, v in out.items() if k in busy}


def fetch_retry(sym, year, month, keep_zero=False, tries=3):
    err = None
    for i in range(tries):
        try:
            return fetch_month(sym, year, month, keep_zero)
        except Exception as e:  # noqa
            err = e
            time.sleep(20)
    raise err


def cmd_check(_a):
    con = open_db()
    ok = True
    # 1) 形式の確認: 全銘柄の1か月分が、検証と価格帯の判定に通ること
    probe = PROBE
    print(f"[形式] {probe[0]}年{probe[1]}月の1時間足を、全銘柄で取得して検証します")
    for sym in FD.RANGES:
        try:
            rows = fetch_retry(sym, *probe)
            if not rows:
                raise ValueError("データが空です")
            d = FD.detect_divisor(sym, rows)
            print(f"OK {sym}: 取引のある足 {len(rows)}本 桁=1/{d} 始値={rows[0][1] / d}")
        except Exception as e:  # noqa
            ok = False
            print(f"NG {sym}: {e}")
    # 2) 既存の1分足から作った1時間足と一致するか
    names = ("買値始値", "買値高値", "買値安値", "買値終値", "売値始値", "売値高値", "売値安値", "売値終値")
    for sym in ("XAGUSD", "USDJPY"):
        has = con.execute("SELECT COUNT(*) FROM m1 WHERE symbol=? AND ts>=? AND ts<?",
                          (sym, *month_range(*probe))).fetchone()[0]
        if not has:
            continue
        try:
            full = fetch_retry(sym, *probe, keep_zero=True)
            kept = [r for r in full if not is_idle((r[0], r[1], r[4], r[3], r[2], r[9]))]
            agg = aggregate_m1(con, sym, *probe)
        except Exception as e:  # noqa
            ok = False
            print(f"NG {sym}(照合): {e}")
            continue
        hrows = {r[0]: r[1:9] for r in kept}
        common = sorted(set(hrows) & set(agg))
        days_h = {t // 86400 for t in hrows}
        days_m = {t // 86400 for t in agg}
        m1_gap_days = len(days_h - days_m)
        extra = [t for t in hrows if t not in agg]
        missing = [t for t in agg if t not in hrows]
        print(f"[照合] {sym}: 1時間足(全て) {len(full)}本 / 取引のない時間を除いた足 {len(kept)}本 / "
              f"1分足から作成 {len(agg)}本 / 共通 {len(common)}本")
        if m1_gap_days:
            print(f"  注意: 1分足のDBに、{m1_gap_days}日分の抜けがあります(1時間足にはある日)。この銘柄の件数の照合は、参考です")
        print(f"  1時間足にあって、1分足にない時間: {len(extra)}本 / 1分足にあって、1時間足にない時間: {len(missing)}本")
        if not m1_gap_days and (len(extra) + len(missing)) > 0.01 * max(len(agg), 1):
            ok = False
            print("  NG: 1分足に抜けがないのに、時間が1%を超えて一致しません")
        if not common:
            ok = False
            print("  共通する時刻がありません(時刻の基準が違う可能性)")
            continue
        for k, nm in enumerate(names):
            eq = sum(1 for t in common if hrows[t][k] == agg[t][k])
            diff = max(abs(hrows[t][k] - agg[t][k]) for t in common)
            print(f"  {nm}: 完全一致 {eq / len(common) * 100:.1f}% / 最大のずれ {diff}")
            if k != 0 and k != 4 and eq / len(common) < 0.999:
                ok = False
        # 始値のずれの内訳(週明けの最初の足か)
        prev_close = {}
        last = None
        for r in sorted(full):
            prev_close[r[0]] = last
            last = r[4]
        bad = [t for t in common if hrows[t][0] != agg[t][0]]
        gap_first = 0
        lines = []
        for t in bad:
            gap_hours = (t - max([u for u in common if u < t], default=t)) / 3600
            gap_first += int(gap_hours >= 6)
            if len(lines) < 5:
                d = dt.datetime.fromtimestamp(t, UTC)
                lines.append(f"    {d:%m-%d %H:%M}({'月火水木金土日'[d.weekday()]}) 1時間足の始値 {hrows[t][0]} / 1分足の始値 {agg[t][0]} / "
                             f"直前の終値 {prev_close.get(t)} / 直前の足から{gap_hours:.0f}時間後")
        print(f"  買値始値がずれた時間 {len(bad)}本(うち、6時間以上の休場明けの最初の足: {gap_first}本)")
        print("  (1分足の始値は、休場明けの最初の足でも、直前の終値になっている。1時間足のほうが、ギャップを反映した実際の始値)")
        for ln in lines:
            print(ln)
    print("\n結果: 問題なし" if ok else "\n結果: 要確認(上のNG・一致率を確認してください)")
    return 0 if ok else 1


def months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def safe_fetch(sym, y, m):
    try:
        return (sym, y, m, fetch_month(sym, y, m), None)
    except Exception as e:  # noqa
        return (sym, y, m, None, str(e))


def cmd_run(a):
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else list(FD.RANGES)
    for sym in syms:
        if sym not in FD.RANGES:
            print(f"未対応の銘柄です: {sym}")
            return 1
    start = dt.date.fromisoformat(a.start)
    today = dt.datetime.now(UTC).date()
    end = (today.replace(day=1) - dt.timedelta(days=1))  # 前月まで(当月は未完了)
    con = open_db()
    todo = []
    for sym in syms:
        done = {r[0] for r in con.execute("SELECT ym FROM h1_months WHERE symbol=?", (sym,))}
        todo += [(sym, y, m) for y, m in months(start, end) if f"{y}-{m:02d}" not in done]
    print(f"未取得 {len(todo)}か月(同時{a.workers}本)", flush=True)
    stats = {s: [0, 0] for s in syms}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(safe_fetch, *t) for t in todo]
        for k, fu in enumerate(as_completed(futs), start=1):
            sym, y, m, rows, err = fu.result()
            ym = f"{y}-{m:02d}"
            if err:
                stats[sym][1] += 1
                print(f"  失敗 {sym} {ym} ({k}/{len(todo)}, {time.time() - t0:.0f}秒): {err[-80:]}", flush=True)
                continue
            if rows:
                FD.get_divisor(con, sym, rows)
                con.executemany("INSERT OR REPLACE INTO h1 VALUES(?,?,?,?,?,?,?,?,?,?,?)", [(sym, *r) for r in rows])
                con.execute("INSERT OR REPLACE INTO h1_months VALUES(?,?,?,?)", (sym, ym, "ok", len(rows)))
            else:
                con.execute("INSERT OR REPLACE INTO h1_months VALUES(?,?,?,?)", (sym, ym, "empty", 0))
            con.commit()
            stats[sym][0] += 1
            print(f"  成功 {sym} {ym} ({k}/{len(todo)}, {time.time() - t0:.0f}秒)", flush=True)
    failed = sum(v[1] for v in stats.values())
    for sym, (ok, ng) in stats.items():
        print(f"[{sym}] 終了: 取得 {ok}か月 / 失敗 {ng}か月", flush=True)
    return 2 if failed else 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--symbols")
    r.add_argument("--start", default="2021-01-01")
    r.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    sys.exit({"check": cmd_check, "run": cmd_run}[a.cmd](a))


if __name__ == "__main__":
    main()
