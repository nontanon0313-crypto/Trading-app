#!/usr/bin/env python3
"""仮想売買(ペーパートレード)。口座なしで、ブレイクの売買を前向きに検証する。

  python papertrade.py selftest          # 研究用の売買(breakout.py)と同じ結果になるか確認(探索期間のデータ)
  python papertrade.py init              # 前向き検証の開始時刻を記録(1回だけ)
  python papertrade.py update            # 最新のデータで全ての組み合わせの売買を再現し、開始以降の損益を表示

仕組み:
  - 全ての組み合わせ(時間足 × 抜けの定義)について、売買ルールを最新のデータまで再現する。
    ルールはbreakout.pyと同じ: ブレイクでエントリーし、逆方向のブレイクで決済(ドテン)、損切りなし、
    約定は条件が成立した足の次の足の始値(買いはask、売りはbid)。
  - 「開始時刻」以降にエントリーした売買だけを、前向きの結果として数える。開始前の売買は、状態をそろえるためだけに使う。
  - 価格はDBの1分足(fetch_dukascopy.pyで更新)を使う。データの反映は最大2日遅れる(売買の約定価格は、実際の足の始値なので、
    後から反映されても、結果は同じ)。
  - 口座がないため、これは仮想の売買であり、実際の約定のずれ(スリッページ)や拒否は含まない。
"""
import argparse
import csv
import datetime as dt
import os
import sqlite3
import sys

import numpy as np

import breakout as B
import research as R

HISTORY_DAYS = 1100   # 状態をそろえるために再現する期間(日)


def simulate_full(up, dn, n):
    """B.simulateと同じ判定で、決済済みの売買に加えて、保有中のポジションと、次の足で実行する予定のシグナルを返す。"""
    both = up & dn
    idx = np.flatnonzero((up | dn) & ~both)
    pos = 0
    entry = -1
    trades = []
    pending = None
    for i in idx:
        e = i + 1
        direction = 1 if up[i] else -1
        if e >= n:
            if pos != direction:
                pending = direction
            break
        if direction == 1:
            if pos == 1:
                continue
            if pos == -1:
                trades.append((-1, entry, e))
            pos = 1
            entry = e
        else:
            if pos == -1:
                continue
            if pos == 1:
                trades.append((1, entry, e))
            pos = -1
            entry = e
    open_pos = (pos, entry) if pos != 0 else None
    return trades, open_pos, pending


def load_recent(con, sym, days):
    """DBの最新から遡って days 日分の1分足を読み込む(最終テスト用期間の制限は適用しない)。"""
    r = con.execute("SELECT v FROM meta WHERE k=?", (f"divisor_{sym}",)).fetchone()
    if not r:
        raise SystemExit(f"{sym}のデータがありません")
    div = float(r[0])
    last = con.execute("SELECT MAX(ts) FROM m1 WHERE symbol=?", (sym,)).fetchone()[0]
    t0 = last - days * 86400
    rows = con.execute("SELECT ts,bo,bh,bl,bc,ao,ah,al,ac FROM m1 WHERE symbol=? AND ts>=? ORDER BY ts",
                       (sym, t0)).fetchall()
    arr = np.array(rows, dtype=np.int64)
    m = {"ts": arr[:, 0]}
    for k, name in enumerate(("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac"), start=1):
        m[name] = arr[:, k].astype(np.float64) / div
    return m


def replay(m1, start_ts):
    """全ての組み合わせの売買を再現する。戻り値: [{tf, def, closed:[...], open:..., pending:...}]"""
    out = []
    for tf in B.TIMEFRAMES:
        bars = R.resample(m1, tf)
        n = len(bars["ts"])
        if n < 500:
            continue
        hp, lp = B.zigzag_levels(bars["bh"], bars["bl"])
        variants = B.break_variants(bars["bh"], bars["bl"], bars["bc"], hp, lp)
        for name, (up, dn) in variants.items():
            trades, open_pos, pending = simulate_full(up, dn, n)
            fwd = [t for t in trades if bars["ts"][t[1]] >= start_ts]
            res = {"tf": tf, "def": name, "bars": bars, "n": n, "open": None, "pending": pending, "closed": []}
            if fwd:
                d, net, gross, cost, mae, hold, years = B.trade_results(fwd, bars)
                res["closed"] = [(int(bars["ts"][t[1]]), int(bars["ts"][t[2]]), int(dd), float(nn))
                                 for t, dd, nn in zip(fwd, d, net)]
            if open_pos and bars["ts"][open_pos[1]] >= start_ts:
                dpos, e = open_pos
                last_bid, last_ask = bars["bc"][-1], bars["ac"][-1]
                ep = bars["ao"][e] if dpos == 1 else bars["bo"][e]
                xp = last_bid if dpos == 1 else last_ask
                unreal = ((xp - ep) if dpos == 1 else (ep - xp)) / ep * 1e4
                res["open"] = (int(bars["ts"][e]), int(dpos), float(ep), float(unreal))
            out.append(res)
    return out


def fmt(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def cmd_selftest(a):
    """研究用(breakout.py)と同じ売買になるか確認する。探索期間のデータを使う。"""
    con = sqlite3.connect(R.DB_PATH)
    m1 = R.load_1m(con, a.symbol, *R.EXPLORE)
    bad = tot = 0
    for tf in B.TIMEFRAMES:
        bars = R.resample(m1, tf)
        n = len(bars["ts"])
        if n < 500:
            continue
        hp, lp = B.zigzag_levels(bars["bh"], bars["bl"])
        for name, (up, dn) in B.break_variants(bars["bh"], bars["bl"], bars["bc"], hp, lp).items():
            t1, _ = B.simulate(up, dn, n)
            t2, _, _ = simulate_full(up, dn, n)
            tot += 1
            if t1 != t2:
                bad += 1
    print(f"研究用の売買との一致: {tot - bad}/{tot} 組み合わせ")
    return 0 if bad == 0 else 1


def cmd_init(a):
    con = sqlite3.connect(R.DB_PATH)
    key = f"paper_start_{a.symbol}"
    r = con.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    if r:
        print(f"すでに開始済みです: {fmt(int(r[0]))} (UTC)")
        return 0
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, str(now)))
    con.commit()
    print(f"前向き検証を開始しました: {fmt(now)} (UTC)。これ以降にエントリーした売買だけを数えます")
    return 0


def cmd_update(a):
    con = sqlite3.connect(R.DB_PATH)
    r = con.execute("SELECT v FROM meta WHERE k=?", (f"paper_start_{a.symbol}",)).fetchone()
    if not r:
        raise SystemExit("先に python papertrade.py init を実行してください")
    start = int(r[0])
    m1 = load_recent(con, a.symbol, HISTORY_DAYS)
    res = replay(m1, start)
    last = int(m1["ts"][-1])
    print(f"[{a.symbol}] 前向き検証の開始: {fmt(start)} / データの最新: {fmt(last)} (UTC)")
    lag = (dt.datetime.now(dt.timezone.utc).timestamp() - last) / 3600
    if lag > 72:
        print(f"注意: データが{lag / 24:.1f}日前までしかありません。python fetch_dukascopy.py run で更新してください")
    allnet = [c[3] for x in res for c in x["closed"]]
    n_open = sum(1 for x in res if x["open"])
    n_pend = sum(1 for x in res if x["pending"])
    print(f"全{len(res)}組み合わせ: 決済済み {len(allnet)}回 / 保有中 {n_open}組 / 次の足で実行予定のシグナル {n_pend}組")
    if allnet:
        print(f"決済済みの全売買: 平均 {np.mean(allnet):+.1f}bps / 合計 {np.sum(allnet):+.0f}bps")
    rows = [x for x in res if x["closed"] or x["open"] or x["pending"]]
    if rows:
        print("\n足 | 定義 | 決済済み回数 | 平均損益(bps) | 合計(bps) | 保有中(エントリー日時 方向 価格 含み損益bps) | 予定シグナル")
        for x in rows:
            nets = [c[3] for c in x["closed"]]
            o = x["open"]
            ostr = f"{fmt(o[0])} {'買い' if o[1] == 1 else '売り'} {o[2]:.3f} {o[3]:+.0f}" if o else "-"
            pstr = ("買い" if x["pending"] == 1 else "売り") if x["pending"] else "-"
            mean = f"{np.mean(nets):+.1f}" if nets else "-"
            tot = f"{np.sum(nets):+.0f}" if nets else "-"
            print(f"{x['tf']}分 | {x['def']} | {len(nets)} | {mean} | {tot} | {ostr} | {pstr}")
    else:
        print("\nまだ取引はありません。データが更新されると、ここに表示されます。")
    os.makedirs(R.OUT_DIR, exist_ok=True)
    path = os.path.join(R.OUT_DIR, f"paper_{a.symbol}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tf", "def", "entry_time", "exit_time", "direction", "net_bps"])
        for x in res:
            for c in x["closed"]:
                w.writerow([x["tf"], x["def"], fmt(c[0]), fmt(c[1]), c[2], round(c[3], 2)])
    print(f"\n(決済済みの売買は {path} に保存しました)")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("selftest", "init", "update"):
        s = sub.add_parser(name)
        s.add_argument("--symbol", default="XAGUSD")
    a = p.parse_args()
    sys.exit({"selftest": cmd_selftest, "init": cmd_init, "update": cmd_update}[a.cmd](a))


if __name__ == "__main__":
    main()
