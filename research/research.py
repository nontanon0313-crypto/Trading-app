#!/usr/bin/env python3
"""シグナル検証ツール(グループ1)。標準ライブラリ+numpyのみ。

  python research.py explore [--symbol XAGUSD]   # 探索期間(2021〜2023年)で全シグナルを検証
  python research.py confirm [--symbol XAGUSD]   # 探索で合格した候補だけを確認期間(2024〜2025年)で1回検証

検証の約束事:
  - エントリーはシグナルが確定した次の足の始値。買いは売値(ask)、売りは買値(bid)で約定。
  - 決済はエントリーからh本後の足の終値(買いはbid、売りはask)。h = 4, 16, 64本。
  - 買い・売りの両方向を別々に評価する。
  - 同じ条件の重なったシグナルは、保有期間が重ならないものだけを数える。
  - 値動きの予測力は、コストを含まない中値(買値と売値の平均)どうしの変化で評価する。
    比較の基準は「同じ環境の全ての足でエントリーした場合の平均」。基準との差(超過)で有意性を見る。
    (売買コストの大小を、予測力と取り違えないため。時間帯でスプレッドが変わるため重要)
  - コストは、エントリー時とエグジット時の実際のスプレッドの半分ずつ(=スプレッド1回分)。
    コスト1倍・2倍・3倍を引いた後の平均を併記する。
  - 多重検定はBenjamini-Hochberg法(q=0.05)で補正する。
  - 2026年1月以降のデータは、このツールからは一切読み込まない。
"""
import argparse
import csv
import datetime as dt
import math
import os
import sqlite3
import sys
import time

import numpy as np

import env
import rules

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "candles.sqlite")
OUT_DIR = os.path.join(HERE, "results")

UTC = dt.timezone.utc


def epoch(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=UTC).timestamp())


EXPLORE = (epoch(2021, 1, 1), epoch(2024, 1, 1))
CONFIRM = (epoch(2024, 1, 1), epoch(2026, 1, 1))
LOCK_END = epoch(2026, 1, 1)  # これ以降のデータは読み込まない(最終テスト用)

TIMEFRAMES = (5, 15, 60, 240, 1440)  # 分
HORIZONS = (4, 16, 64)               # 本
MIN_EVENTS = 100                     # 重ならないシグナルがこれ未満なら検証しない
FDR_Q = 0.05


# ---------- データ読み込み ----------
def load_1m(con, sym, t0, t1):
    if t1 > LOCK_END:
        raise SystemExit("2026年以降のデータは最終テスト用のため読み込めません")
    r = con.execute("SELECT v FROM meta WHERE k=?", (f"divisor_{sym}",)).fetchone()
    if not r:
        raise SystemExit(f"{sym}のデータがありません。先に fetch_dukascopy.py run を実行してください")
    div = float(r[0])
    n = con.execute("SELECT COUNT(*) FROM m1 WHERE symbol=? AND ts>=? AND ts<?",
                    (sym, t0, t1)).fetchone()[0]
    if n == 0:
        raise SystemExit(f"{sym}の指定期間にデータがありません")
    arr = np.empty((n, 9), dtype=np.int64)
    cur = con.execute("SELECT ts,bo,bh,bl,bc,ao,ah,al,ac FROM m1 "
                      "WHERE symbol=? AND ts>=? AND ts<? ORDER BY ts", (sym, t0, t1))
    i = 0
    while True:
        rows = cur.fetchmany(200000)
        if not rows:
            break
        a = np.array(rows, dtype=np.int64)
        arr[i:i + len(a)] = a
        i += len(a)
    m = {"ts": arr[:, 0]}
    for k, name in enumerate(("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac"), start=1):
        m[name] = arr[:, k].astype(np.float64) / div
    return m


def resample(m, tf_min):
    sec = tf_min * 60
    bucket = m["ts"] // sec
    idx = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    last = np.r_[idx[1:] - 1, len(bucket) - 1]
    out = {"ts": bucket[idx] * sec}
    for s in ("b", "a"):
        out[s + "o"] = m[s + "o"][idx]
        out[s + "c"] = m[s + "c"][last]
        out[s + "h"] = np.maximum.reduceat(m[s + "h"], idx)
        out[s + "l"] = np.minimum.reduceat(m[s + "l"], idx)
    return out


# ---------- 将来リターン ----------
def forward(bars, h):
    """各足iでシグナルが出た場合の、中値どうしの変化(買い・売り, bps)と、実際のコスト(bps)。長さ n-h。
    コスト = エントリーとエグジットのスプレッドの半分ずつ(買いはask買い・bid売り、売りはその逆)。"""
    n = len(bars["ts"])
    ea = bars["ao"][1:n - h + 1]
    eb = bars["bo"][1:n - h + 1]
    xb = bars["bc"][h:n]
    xa = bars["ac"][h:n]
    mid_in = (ea + eb) / 2
    mid_out = (xa + xb) / 2
    buy = (mid_out - mid_in) / mid_in * 1e4
    sell = -buy
    cost = (((ea - eb) + (xa - xb)) / 2) / mid_in * 1e4
    return buy, sell, cost


def deoverlap(idx, gap):
    out = []
    last = -10 ** 12
    for i in idx:
        if i - last >= gap:
            out.append(i)
            last = i
    return np.array(out, dtype=np.int64)


def norm_p_one_sided(t):
    return 0.5 * math.erfc(t / math.sqrt(2))


def test_one(ret, cost, ev_idx, h, base_mean, years):
    sel = deoverlap(ev_idx, h)
    if len(sel) < MIN_EVENTS:
        return None
    r = ret[sel]
    n = len(r)
    mean = float(r.mean())
    sd = float(r.std(ddof=1))
    if sd == 0:
        return None
    excess = mean - base_mean
    t = excess / (sd / math.sqrt(n))
    c = cost[sel]
    cm = float(c.mean())
    net = r - c
    ys = years[sel]
    pos = tot = 0
    for y in np.unique(ys):
        mk = ys == y
        if mk.sum() >= 30:
            tot += 1
            pos += int(net[mk].mean() > 0)
    return {"n": n, "gross": mean, "base": base_mean, "excess": excess, "t": t,
            "p": norm_p_one_sided(t), "cost": cm, "net1x": mean - cm, "net2x": mean - 2 * cm,
            "net3x": mean - 3 * cm, "years_pos": pos, "years_tot": tot}


def load_macro(con):
    """DBからファンダメンタルズ(金利・VIX・イベント)を読み込む。未取得の項目は含まれない。"""
    macro = {}
    try:
        for key, name in (("DFII10", "金利"), ("VIXCLS", "VIX")):
            rows = con.execute("SELECT date,value FROM macro WHERE series=? ORDER BY date", (key,)).fetchall()
            if rows:
                days = np.array([(dt.date.fromisoformat(d) - dt.date(1970, 1, 1)).days for d, _ in rows],
                                dtype=np.int64)
                vals = np.array([v for _, v in rows], dtype=float)
                macro[name] = (days, env.real_rate_state(vals) if key == "DFII10" else env.vix_state(vals))
        ev = [r[0] for r in con.execute("SELECT ts FROM events ORDER BY ts")]
        if ev:
            macro["イベント"] = np.array(ev, dtype=np.int64)
    except sqlite3.OperationalError:
        pass
    return macro


ENV_STATES = ((1, "上昇"), (-1, "下降"), (0, "レンジ"))


def run_tests(m1, symbol, only=None, verbose=True, macro=None):
    """全シグナル × 環境 × 時間足 × 保有本数 × 方向 を検証し、結果行のリストを返す。
    環境認識は、自足・上位1段・上位2段のトレンド(上昇/下降/レンジ)を1つずつ条件にする。"""
    results = []
    allbars, states = {}, {}
    for tf in TIMEFRAMES:
        b = resample(m1, tf)
        if len(b["ts"]) < 500:
            continue
        allbars[tf] = b
        states[tf] = env.zigzag_trend(b["bh"], b["bl"])
    tfs = [tf for tf in TIMEFRAMES if tf in allbars]
    for pos, tf in enumerate(tfs):
        t0 = time.time()
        bars = allbars[tf]
        n = len(bars["ts"])
        sig = {"ts": bars["ts"], "o": bars["bo"], "h": bars["bh"], "l": bars["bl"], "c": bars["bc"]}
        events = rules.g1_events(sig, symbol, tf * 60)
        years = bars["ts"].astype("datetime64[s]").astype("datetime64[Y]").astype(np.int64) + 1970
        conds = [("環境なし", None)]
        dims = [("自足", states[tf], ENV_STATES)]
        for label, up in (("上位1", pos + 1), ("上位2", pos + 2)):
            if up < len(tfs):
                ht = tfs[up]
                dims.append((label, env.map_to_lower(bars["ts"], tf * 60, allbars[ht]["ts"],
                                                     ht * 60, states[ht]), ENV_STATES))
        if macro:
            if "金利" in macro:
                days, st = macro["金利"]
                dims.append(("金利", env.map_daily_to_bars(bars["ts"], tf * 60, days, st),
                             ((1, "上昇"), (-1, "低下"))))
            if "VIX" in macro:
                days, st = macro["VIX"]
                dims.append(("VIX", env.map_daily_to_bars(bars["ts"], tf * 60, days, st),
                             ((1, "高"), (-1, "低"))))
            if "イベント" in macro:
                dims.append(("イベント", env.event_state(bars["ts"], tf * 60, macro["イベント"]),
                             ((0, "通常"), (1, "事前"), (2, "事後"))))
        for label, arr, sts in dims:
            for v, lab in sts:
                conds.append((f"{label}:{lab}", arr == v))
        for h in HORIZONS:
            buy, sell, cost = forward(bars, h)
            m = len(buy)
            rets = {"買い": buy, "売り": sell}
            base = {}
            for cname, mask in conds:
                for dname, ret in rets.items():
                    sel = ret if mask is None else ret[mask[:m]]
                    base[(cname, dname)] = float(sel.mean()) if len(sel) else None
            for name, e in events.items():
                for cname, mask in conds:
                    if only is not None and (name, tf, h, cname) not in only:
                        continue
                    ee = e[:m] if mask is None else (e[:m] & mask[:m])
                    idx = np.flatnonzero(ee)
                    if len(idx) < MIN_EVENTS:
                        continue
                    for dname, ret in rets.items():
                        bm = base[(cname, dname)]
                        if bm is None:
                            continue
                        r = test_one(ret, cost, idx, h, bm, years[:m])
                        if r:
                            r.update({"rule": name, "tf": tf, "h": h, "dir": dname, "env": cname})
                            results.append(r)
        if verbose:
            print(f"  {tf}分足: 完了 ({time.time() - t0:.0f}秒)", flush=True)
    return results


def bh_flags(results, q=FDR_Q):
    m = len(results)
    order = sorted(range(m), key=lambda i: results[i]["p"])
    kmax = 0
    for rank, i in enumerate(order, start=1):
        if results[i]["p"] <= q * rank / m:
            kmax = rank
    flags = [False] * m
    for rank, i in enumerate(order, start=1):
        if rank <= kmax:
            flags[i] = True
    return flags


COLS = ["rule", "env", "tf", "h", "dir", "n", "gross", "base", "excess", "t", "p", "cost",
        "net1x", "net2x", "net3x", "years_pos", "years_tot", "bh_pass"]


def save_csv(path, results):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for r in results:
            w.writerow([r.get(c, "") if not isinstance(r.get(c), float) else round(r[c], 5)
                        for c in COLS])


def show(results, title, k=15):
    print(f"\n{title}")
    print("シグナル | 環境 | 足 | 本数 | 方向 | 回数 | 値動き(bps) | 基準 | 超過 | t | コスト | 1倍後 | 3倍後 | 年プラス")
    for r in results[:k]:
        print(f"{r['rule']} | {r['env']} | {r['tf']}分 | {r['h']} | {r['dir']} | {r['n']} | "
              f"{r['gross']:.1f} | {r['base']:.1f} | {r['excess']:.1f} | {r['t']:.2f} | "
              f"{r['cost']:.1f} | {r['net1x']:.1f} | {r['net3x']:.1f} | {r['years_pos']}/{r['years_tot']}")


def cmd_explore(a):
    con = sqlite3.connect(DB_PATH)
    m1 = load_1m(con, a.symbol, *EXPLORE)
    d0 = dt.datetime.fromtimestamp(int(m1["ts"][0]), UTC).date()
    d1 = dt.datetime.fromtimestamp(int(m1["ts"][-1]), UTC).date()
    print(f"[{a.symbol}] 探索期間のデータ: {d0}〜{d1} / 1分足 {len(m1['ts']):,}本", flush=True)
    if d1 < dt.date(2023, 12, 1) or d0 > dt.date(2021, 1, 15):
        print("注意: 探索期間(2021〜2023年)のデータが最後まで揃っていません。"
              "取得の完了後に再実行してください", flush=True)
    macro = load_macro(con)
    names = "、".join(["トレンド(自足・上位1・上位2)"] + list(macro))
    print(f"環境認識: {names}", flush=True)
    if len(macro) < 3:
        print("注意: ファンダメンタルズの一部が未取得です(python fetch_macro.py run)", flush=True)
    res = run_tests(m1, a.symbol, macro=macro)
    if not res:
        print("検証できるシグナルがありませんでした(データ不足)")
        return 1
    flags = bh_flags(res)
    for r, f in zip(res, flags):
        r["bh_pass"] = int(f)
    res.sort(key=lambda r: -r["t"])
    save_csv(os.path.join(OUT_DIR, f"explore_{a.symbol}.csv"), res)
    passed = [r for r in res if r["bh_pass"]]
    cand = [r for r in passed if r["net1x"] > 0 and r["net3x"] > 0]
    print(f"\n検証数: {len(res)} / 多重検定補正後も有意: {len(passed)} / "
          f"うちコスト1倍後も3倍後もプラス: {len(cand)}")
    show(res, "t値の上位(参考。補正前の見かけの強さ)")
    if cand:
        show(cand, "候補(補正後も有意かつコスト3倍でもプラス)")
    else:
        print("\n探索期間で、補正後も有意な候補はありませんでした")
    return 0


def cmd_confirm(a):
    path = os.path.join(OUT_DIR, f"explore_{a.symbol}.csv")
    if not os.path.exists(path):
        raise SystemExit("先に explore を実行してください")
    cand = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["bh_pass"] == "1" and float(r["net1x"]) > 0 and float(r["net3x"]) > 0:
                cand.append((r["rule"], r["env"], int(r["tf"]), int(r["h"]), r["dir"]))
    if not cand:
        print("探索期間の合格候補がないため、確認は行いません")
        return 0
    con = sqlite3.connect(DB_PATH)
    m1 = load_1m(con, a.symbol, *CONFIRM)
    only = {(c[0], c[2], c[3], c[1]) for c in cand}
    res = run_tests(m1, a.symbol, only=only, verbose=False, macro=load_macro(con))
    res = [r for r in res if (r["rule"], r["env"], r["tf"], r["h"], r["dir"]) in set(cand)]
    thr = 0.05 / len(cand)
    for r in res:
        r["bh_pass"] = int(r["p"] < thr and r["net1x"] > 0 and r["net3x"] > 0 and r["excess"] > 0)
    res.sort(key=lambda r: -r["t"])
    save_csv(os.path.join(OUT_DIR, f"confirm_{a.symbol}.csv"), res)
    ok = [r for r in res if r["bh_pass"]]
    print(f"確認した候補: {len(cand)} / 確認期間でも合格: {len(ok)} (基準: p<{thr:.4f}、コスト1倍後>0、3倍後>0、超過>0)")
    show(res, "確認期間の結果", k=30)
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("explore", "confirm"):
        s = sub.add_parser(name)
        s.add_argument("--symbol", default="XAGUSD")
    a = p.parse_args()
    sys.exit({"explore": cmd_explore, "confirm": cmd_confirm}[a.cmd](a))


if __name__ == "__main__":
    main()
