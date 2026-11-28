#!/usr/bin/env python3
"""トレンドを組み込んだ売買の検証。1時間足のデータ(fetch_hourly.py)を使う。

  python trend.py explore                       # 探索期間(2021〜2023年)で、トレンドあり・なしを全て比較
  python trend.py detail --tf 60 --htf 1440 --defn 維持1 [--mode base]   # 1つの組み合わせの、年・月・日の収益

定義:
  - トレンド = より大きな時間足の、現在の1波の向き。波は、現在のレッグの値幅に対して38.2%を超えて逆行したら確定する
    (これまでと同じ定義)。上昇の波なら上昇トレンド、下降の波なら下降トレンド。その足が確定した時点の向きだけを使う。
  - トレンドあり: 小さな時間足のブレイクを、大きな時間足のトレンドの向きにだけエントリーする(上昇なら買いのみ、下降なら売りのみ)。
    決済は、小さな時間足の逆ブレイク、または、大きな時間足の波の向きが、ポジションと逆に変わったとき。
    決済と同じ足で、トレンドの向きと合うエントリーの条件が成立していれば、そのまま入る(ドテン)。
  - トレンドなし(base): 常にドテン(これまでの売買)。
  - 約定は、条件が成立した足の次の足の始値(買いはask、売りはbid)。損切りなし。
  - 収益: 銘柄ごとに、売買の損益を足ごとに分けて(エントリーのスプレッド・決済のスプレッドを含む)、日・月・年で複利にする。
    8銘柄に資金を等しく配分し、毎日配分を戻す。レバレッジなし。
"""
import argparse
import csv
import datetime as dt
import math
import os
import sqlite3
import sys

import numpy as np

import breakout as B
import env
import research as R

SMALL_TFS = (60, 240, 1440)
PAIRS = ((60, 240), (60, 1440), (240, 1440))   # (小さな時間足, 大きな時間足)


def zigzag_dir(h, l, ratio=B.RATIO):
    """各足の確定時点での、現在の波(レッグ)の向き。+1=上昇、-1=下降、0=最初の節目が確定するまでは不明。"""
    n = len(h)
    dirs = np.zeros(n, dtype=np.int8)
    if n == 0:
        return dirs
    d = 1
    start = l[0]
    ext = h[0]
    seen = False
    for i in range(1, n):
        if d == 1:
            if h[i] > ext:
                ext = h[i]
            if l[i] <= ext - ratio * (ext - start):
                d, start, ext, seen = -1, ext, l[i], True
        else:
            if l[i] < ext:
                ext = l[i]
            if h[i] >= ext + ratio * (start - ext):
                d, start, ext, seen = 1, ext, h[i], True
        dirs[i] = d if seen else 0
    return dirs


def simulate_trend(up, dn, htf, n):
    """トレンドありの売買。戻り値: [(方向, エントリー足, 決済足)](決済済みのみ)。
    足iの終値で条件を判定し、次の足(i+1)の始値で約定する。"""
    trades = []
    pos = 0
    entry = -1
    for i in range(n - 1):
        e = i + 1
        u, d_ = bool(up[i]), bool(dn[i])
        if u and d_:
            u = d_ = False            # 上下が同じ足で成立した足は、順序が判断できないため無視
        trend = int(htf[i])
        if pos == 1 and (d_ or trend == -1):
            trades.append((1, entry, e))
            pos = 0
        elif pos == -1 and (u or trend == 1):
            trades.append((-1, entry, e))
            pos = 0
        if pos == 0:
            if u and trend == 1:
                pos, entry = 1, e
            elif d_ and trend == -1:
                pos, entry = -1, e
    return trades


def bar_log_returns(trades, bars):
    """売買の損益を、足ごとの対数収益に分ける。足ごとの合計が、その売買の損益(exp(合計)-1)と一致する。
    売買の価値は、エントリー時の資金を1として、買いは「現在値/エントリー価格」、売りは「1+(エントリー価格-現在値)/エントリー価格」。
    足の途中の評価は、終値(買いはbid、売りはask)、決済の足は、決済の始値で評価する。"""
    n = len(bars["ts"])
    lr = np.zeros(n)
    ao, bo, ac, bc = bars["ao"], bars["bo"], bars["ac"], bars["bc"]
    for d, e, x in trades:
        v = np.empty(x - e + 1)
        if d == 1:
            v[:-1] = bc[e:x] / ao[e]
            v[-1] = bo[x] / ao[e]
        else:
            v[:-1] = 2.0 - ac[e:x] / bo[e]
            v[-1] = 2.0 - ao[x] / bo[e]
        lr[e:x + 1] += np.diff(np.log(v), prepend=0.0)
    return lr


def daily_from_bars(lr, ts, d0, nd):
    """足ごとの対数収益を、UTCの日ごとに合計して、長さndの配列にする(d0=最初の日の通し番号)。"""
    out = np.zeros(nd)
    idx = (ts // 86400 - d0).astype(np.int64)
    ok = (idx >= 0) & (idx < nd)
    np.add.at(out, idx[ok], lr[ok])
    return out


def signflip_h1(m, seed=2):
    """比較用: 各1時間足の上下の向きだけをランダムにする(足の大きさの並びは同じ)。スプレッドは、元の足と同じ幅を足す。"""
    bo, bh, bl, bc = m["bo"], m["bh"], m["bl"], m["bc"]
    rc, rh, rl = np.log(bc / bo), np.log(bh / bo), np.log(bl / bo)
    flip = np.random.default_rng(seed).random(len(bo)) < 0.5
    rc2 = np.where(flip, -rc, rc)
    rh2 = np.where(flip, -rl, rh)
    rl2 = np.where(flip, -rh, rl)
    close = bc[0] * np.exp(np.cumsum(rc2))
    opn = np.r_[bc[0], close[:-1]]
    out = {"ts": m["ts"], "bo": opn, "bc": close, "bh": opn * np.exp(rh2), "bl": opn * np.exp(rl2)}
    for k in ("o", "h", "l", "c"):
        out["a" + k] = out["b" + k] + (m["a" + k] - m["b" + k])
    return out


def load_symbol(con, sym, t0, t1, null=False, seed=2):
    m = R.load_1m(con, sym, t0, t1, table="h1")
    if null:
        m = signflip_h1(m, seed)
    bars = {tf: R.resample(m, tf) for tf in SMALL_TFS}
    dirs = {}
    for tf in (240, 1440):
        b = bars[tf]
        dirs[tf] = (zigzag_dir(b["bh"], b["bl"]), b)
    return bars, dirs


def configs():
    """(モード, 小さな時間足, 大きな時間足, 抜けの定義)の一覧"""
    defs = ["ヒゲ", "実体"] + [f"維持{k}" for k in range(1, B.HOLD_MAX + 1)]
    out = []
    for tf in SMALL_TFS:
        for d in defs:
            out.append(("base", tf, 0, d))
    for tf, htf in PAIRS:
        for d in defs:
            out.append(("trend", tf, htf, d))
    return out


def run_symbol(bars, dirs, cfg, d0, nd):
    mode, tf, htf, name = cfg
    b = bars[tf]
    n = len(b["ts"])
    hp, lp = B.zigzag_levels(b["bh"], b["bl"])
    up, dn = B.break_variants(b["bh"], b["bl"], b["bc"], hp, lp)[name]
    if mode == "base":
        trades, _ = B.simulate(up, dn, n)
    else:
        hd, hb = dirs[htf]
        d_small = env.map_to_lower(b["ts"], tf * 60, hb["ts"], htf * 60, hd)
        trades = simulate_trend(up, dn, d_small, n)
    if not trades:
        return np.zeros(nd), np.array([])
    lr = bar_log_returns(trades, b)
    d, net, *_ = B.trade_results(trades, b)
    return daily_from_bars(lr, b["ts"], d0, nd), net


def portfolio_stats(daily_by_symbol, d0):
    """銘柄ごとの日次の対数収益から、等配分(毎日配分を戻す)のポートフォリオの、日・月・年の複利収益を求める。"""
    simple = np.expm1(np.vstack(daily_by_symbol))
    port = simple.mean(axis=0)
    nd = len(port)
    days = [dt.date(1970, 1, 1) + dt.timedelta(days=int(d0 + i)) for i in range(nd)]
    equity = np.cumprod(1 + port)
    peak = np.maximum.accumulate(equity)
    maxdd = float((equity / peak - 1).min())
    months, years = {}, {}
    for r, d in zip(port, days):
        months[(d.year, d.month)] = months.get((d.year, d.month), 1.0) * (1 + r)
        years[d.year] = years.get(d.year, 1.0) * (1 + r)
    m_ret = np.array([v - 1 for v in months.values()])
    active = port[port != 0]
    t = float(port.mean() / (port.std(ddof=1) / math.sqrt(nd))) if port.std() > 0 else 0.0
    return {
        "port": port, "days": days, "months": {k: v - 1 for k, v in months.items()},
        "years": {k: v - 1 for k, v in years.items()}, "maxdd": maxdd, "t": t, "p": R.norm_p_one_sided(t),
        "day_mean": float(port.mean()), "day_pos": float((active > 0).mean()) if len(active) else 0.0,
        "day_worst": float(port.min()), "month_mean": float(m_ret.mean()), "month_median": float(np.median(m_ret)),
        "month_pos": float((m_ret > 0).mean()), "month_worst": float(m_ret.min()), "total": float(equity[-1] - 1),
    }


def evaluate(con, t0, t1, syms, only=None, null=False):
    d0 = t0 // 86400
    nd = (t1 - t0) // 86400
    data = {}
    for sym in syms:
        try:
            data[sym] = load_symbol(con, sym, t0, t1, null=null, seed=2 + len(data))
        except SystemExit:
            continue
    out = []
    for cfg in configs():
        if only is not None and cfg not in only:
            continue
        daily, nets = [], []
        for sym, (bars, dirs) in data.items():
            dly, net = run_symbol(bars, dirs, cfg, d0, nd)
            daily.append(dly)
            nets.append(net)
        st = portfolio_stats(daily, d0)
        allnet = np.concatenate([x for x in nets if len(x)]) if any(len(x) for x in nets) else np.array([])
        st.update({"cfg": cfg, "n_trades": int(len(allnet)),
                   "trade_mean": float(allnet.mean()) if len(allnet) else 0.0, "n_syms": len(data)})
        out.append(st)
    return out


def cfg_label(cfg):
    mode, tf, htf, name = cfg
    return (f"{tf}分足・{name}・トレンドなし" if mode == "base" else f"{tf}分足・{name}・{htf}分足のトレンド")


def pct(x):
    return f"{x * 100:+.1f}%"


def cmd_explore(a):
    con = sqlite3.connect(R.DB_PATH)
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM h1 ORDER BY symbol")]
    if not syms:
        raise SystemExit("1時間足のデータがありません")
    t0, t1 = R.EXPLORE
    res = evaluate(con, t0, t1, syms)
    nul = {r["cfg"]: r for r in evaluate(con, t0, t1, syms, null=True)}
    flags = R.bh_flags([{"p": r["p"]} for r in res])
    for r, f in zip(res, flags):
        r["bh_pass"] = int(f)
    res.sort(key=lambda r: -r["t"])
    os.makedirs(R.OUT_DIR, exist_ok=True)
    path = os.path.join(R.OUT_DIR, "trend_explore.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["mode", "tf", "htf", "def", "n_trades", "trade_mean_bps", "total", "years", "month_mean",
                    "month_pos", "month_worst", "day_mean", "day_pos", "day_worst", "maxdd", "t", "p", "bh_pass"])
        for r in res:
            m, tf, htf, nm = r["cfg"]
            w.writerow([m, tf, htf, nm, r["n_trades"], round(r["trade_mean"], 2), round(r["total"], 4),
                        " ".join(f"{y}:{v:+.3f}" for y, v in sorted(r["years"].items())), round(r["month_mean"], 5),
                        round(r["month_pos"], 3), round(r["month_worst"], 4), round(r["day_mean"], 6),
                        round(r["day_pos"], 3), round(r["day_worst"], 4), round(r["maxdd"], 4), round(r["t"], 3),
                        round(r["p"], 5), r["bh_pass"]])
    passed = [r for r in res if r["bh_pass"] and r["total"] > 0]
    print(f"{len(syms)}銘柄に等配分(毎日配分を戻す・レバレッジなし)/ {len(res)}通り(トレンドあり{sum(1 for r in res if r['cfg'][0] == 'trend')}・なし{sum(1 for r in res if r['cfg'][0] == 'base')}) / "
          f"多重検定補正後も、収益がプラスと言えるもの: {len(passed)}")
    print("\n組み合わせ | 売買 | 1回の平均(bps) | 年ごとの複利収益 | 月: 平均 プラス月 最悪 | 日: 平均 プラス日 最悪 | 最大下落 | t値")
    for r in res[:15]:
        ys = " ".join(f"{y}年{pct(v)}" for y, v in sorted(r["years"].items()))
        print(f"{cfg_label(r['cfg'])} | {r['n_trades']} | {r['trade_mean']:+.1f} | {ys} | {pct(r['month_mean'])} {r['month_pos'] * 100:.0f}% {pct(r['month_worst'])} | "
              f"{pct(r['day_mean'])} {r['day_pos'] * 100:.0f}% {pct(r['day_worst'])} | {pct(r['maxdd'])} | {r['t']:.2f}")
    # トレンドを組み込んだ効果: 同じ小さな時間足・抜けの定義で、トレンドなしとの差。比較用(向きをランダムにしたデータ)でも同じ差を出す。
    # 取引が減ると、コストが減るため、比較用でも差が出る。実データと比較用の差が、トレンドの効果。
    base = {(c[1], c[3]): r for r in res for c in [r["cfg"]] if c[0] == "base"}
    nbase = {(c[1], c[3]): r for c, r in nul.items() if c[0] == "base"}
    print("\nトレンドを組み込んだ効果(トレンドなしとの、期間全体の複利収益の差)。比較用=各足の向きをランダムにしたデータ")
    print("売買 | トレンド | 実データ: 差の平均 高かったもの | 比較用: 差の平均 高かったもの | 実データの差−比較用の差")
    for tf, htf in PAIRS:
        rd, nd_ = [], []
        for r in res:
            m, t, h, nm = r["cfg"]
            if m == "trend" and t == tf and h == htf:
                rd.append(r["total"] - base[(tf, nm)]["total"])
                nd_.append(nul[r["cfg"]]["total"] - nbase[(tf, nm)]["total"])
        print(f"{tf}分足 | {htf}分足 | {pct(float(np.mean(rd)))} {sum(1 for x in rd if x > 0)}/{len(rd)} | "
              f"{pct(float(np.mean(nd_)))} {sum(1 for x in nd_ if x > 0)}/{len(nd_)} | {pct(float(np.mean(rd) - np.mean(nd_)))}")
    print(f"\n(全組み合わせは {path} に保存しました)")
    return 0


def cmd_detail(a):
    con = sqlite3.connect(R.DB_PATH)
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM h1 ORDER BY symbol")]
    cfg = ("base", a.tf, 0, a.defn) if a.mode == "base" else ("trend", a.tf, a.htf, a.defn)
    t0, t1 = R.EXPLORE
    r = evaluate(con, t0, t1, syms, only={cfg})[0]
    print(f"{cfg_label(cfg)} / {r['n_syms']}銘柄に等配分 / 期間全体の複利収益 {pct(r['total'])} / 最大下落 {pct(r['maxdd'])}")
    print("年: " + " ".join(f"{y}年 {pct(v)}" for y, v in sorted(r["years"].items())))
    print("\n月ごとの複利収益(行=年、列=月)")
    print("年 | " + " | ".join(f"{m}月" for m in range(1, 13)))
    for y in sorted({k[0] for k in r["months"]}):
        print(f"{y} | " + " | ".join(pct(r["months"][(y, m)]) if (y, m) in r["months"] else "-" for m in range(1, 13)))
    print(f"\n月: 平均 {pct(r['month_mean'])} / 中央値 {pct(r['month_median'])} / プラスの月 {r['month_pos'] * 100:.0f}% / 最悪 {pct(r['month_worst'])}")
    print(f"日: 平均 {pct(r['day_mean'])} / プラスの日(動いた日のうち) {r['day_pos'] * 100:.0f}% / 最悪 {pct(r['day_worst'])}")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("explore")
    d = sub.add_parser("detail")
    d.add_argument("--tf", type=int, required=True)
    d.add_argument("--htf", type=int, default=0)
    d.add_argument("--defn", required=True)
    d.add_argument("--mode", default="trend", choices=["trend", "base"])
    a = p.parse_args()
    sys.exit({"explore": cmd_explore, "detail": cmd_detail}[a.cmd](a))


if __name__ == "__main__":
    main()
