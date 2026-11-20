#!/usr/bin/env python3
"""ブレイクの検証(単独)。仮置きの数値は使わず、ご指定の定義だけで検証する。

  python breakout.py explore [--symbol XAGUSD]   # 探索期間(2021〜2023年)で検証

定義(ご指示のとおり):
  - 波動: 現在のレッグの値幅に対して38.2%を超えて逆行したら、そのレッグを確定(節目)。上昇・下降とも同じ比率。
  - ブレイク: 直前に確定した高値を上に超えたら上方ブレイク、直前に確定した安値を下に割ったら下方ブレイク。
  - 抜けの判定を3通り検証: ヒゲ(高値/安値が少しでも超えた) / 実体(終値が超えた) /
    維持k(実体で抜けた後、k本の間、終値が抜けた基準の外側に留まった。k=1〜10の全てを見る)
  - 1回の売買: ブレイクでエントリーし、逆方向のブレイクで決済(ドテン)。損切りは設けない。
  - 約定: 条件が成立した足の「次の足の始値」。買いはask、売りはbidで約定(スプレッド込み)。
  - 評価: 売買1回あたりの損益(bps)の平均(期待値)。コストを含まない中値での平均も併記。
  - 環境認識(上位足・ファンダメンタルズ)は、この単独の検証が終わってから個別に加える。
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

import research as R
import rules

TIMEFRAMES = (1, 5, 15, 60, 240, 1440)  # 分(ご指定の時間軸)
HOLD_MAX = 10
MIN_TRADES = 30
RATIO = 0.382


def zigzag_full(h, l, ratio=RATIO):
    """各足の判定に使える「直前に確定した高値・安値」と、その節目を作ったレッグの値幅、節目の通し番号。
    その足より前の足までに確定した節目だけを返す(未来の情報は使わない)。"""
    n = len(h)
    hp = np.full(n, np.nan)
    lp = np.full(n, np.nan)
    hleg = np.full(n, np.nan)
    lleg = np.full(n, np.nan)
    hid = np.zeros(n, dtype=np.int64)
    lid = np.zeros(n, dtype=np.int64)
    if n == 0:
        return hp, lp, hleg, lleg, hid, lid
    d = 1
    start = l[0]
    ext = h[0]
    last_h = last_l = leg_h = leg_l = np.nan
    cnt_h = cnt_l = 0
    for i in range(n):
        hp[i] = last_h
        lp[i] = last_l
        hleg[i] = leg_h
        lleg[i] = leg_l
        hid[i] = cnt_h
        lid[i] = cnt_l
        if i == 0:
            continue
        if d == 1:
            if h[i] > ext:
                ext = h[i]
            if l[i] <= ext - ratio * (ext - start):
                last_h = ext
                leg_h = ext - start
                cnt_h += 1
                d = -1
                start = ext
                ext = l[i]
        else:
            if l[i] < ext:
                ext = l[i]
            if h[i] >= ext + ratio * (start - ext):
                last_l = ext
                leg_l = start - ext
                cnt_l += 1
                d = 1
                start = ext
                ext = h[i]
    return hp, lp, hleg, lleg, hid, lid


def zigzag_levels(h, l, ratio=RATIO):
    """各足の判定に使える「直前に確定した高値・安値」。"""
    hp, lp = zigzag_full(h, l, ratio)[:2]
    return hp, lp


def break_variants(h, l, c, hp, lp):
    """{定義名: (上方ブレイクの真偽配列, 下方ブレイクの真偽配列)}"""
    with np.errstate(invalid="ignore"):
        up_w = np.asarray(h > hp, dtype=bool)
        dn_w = np.asarray(l < lp, dtype=bool)
        up_b = np.asarray(c > hp, dtype=bool)
        dn_b = np.asarray(c < lp, dtype=bool)
    out = {"ヒゲ": (up_w, dn_w), "実体": (up_b, dn_b)}
    for k in range(1, HOLD_MAX + 1):
        out[f"維持{k}"] = (rules._hold(up_b, c, hp, k, up=True), rules._hold(dn_b, c, lp, k, up=False))
    return out


def simulate(up, dn, n):
    """逆方向のブレイクで決済し、同時にドテンする。戻り値: [(方向, エントリー足, 決済足)]。
    同じ足で上下の両方が成立した足は判断できないため無視する(件数も返す)。"""
    both = up & dn
    idx = np.flatnonzero((up | dn) & ~both)
    pos = 0
    entry = -1
    trades = []
    for i in idx:
        e = i + 1
        if e >= n:
            break
        if up[i]:
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
    return trades, int(both.sum())


def trade_results(trades, bars):
    """売買ごとの 純損益・中値損益・コスト・最大逆行(bps)・保有時間(分)・年 を返す。"""
    d = np.array([t[0] for t in trades])
    en = np.array([t[1] for t in trades])
    ex = np.array([t[2] for t in trades])
    ao, bo = bars["ao"], bars["bo"]
    mid = (ao + bo) / 2
    long_ = d == 1
    entry_px = np.where(long_, ao[en], bo[en])
    exit_px = np.where(long_, bo[ex], ao[ex])
    net = np.where(long_, exit_px - entry_px, entry_px - exit_px) / entry_px * 1e4
    gross = np.where(long_, mid[ex] - mid[en], mid[en] - mid[ex]) / mid[en] * 1e4
    mae = np.empty(len(trades))
    bl, ah = bars["bl"], bars["ah"]
    for k in range(len(trades)):
        a, b = en[k], ex[k]
        if long_[k]:
            mae[k] = max(0.0, (entry_px[k] - bl[a:b].min()) / entry_px[k] * 1e4)
        else:
            mae[k] = max(0.0, (ah[a:b].max() - entry_px[k]) / entry_px[k] * 1e4)
    hold_min = (bars["ts"][ex] - bars["ts"][en]) / 60.0
    years = bars["ts"][en].astype("datetime64[s]").astype("datetime64[Y]").astype(np.int64) + 1970
    return d, net, gross, gross - net, mae, hold_min, years


def summarize(net, gross, cost, mae, hold_min, years):
    n = len(net)
    if n < MIN_TRADES:
        return None
    mean = float(net.mean())
    sd = float(net.std(ddof=1))
    gm = float(gross.mean())
    gsd = float(gross.std(ddof=1))
    if sd == 0 or gsd == 0:
        return None
    t = mean / (sd / math.sqrt(n))
    tg = gm / (gsd / math.sqrt(n))
    loss = -net[net < 0].sum()
    pf = float(net[net > 0].sum() / loss) if loss > 0 else float("inf")
    pos = tot = 0
    for y in np.unique(years):
        mk = years == y
        if mk.sum() >= 10:
            tot += 1
            pos += int(net[mk].mean() > 0)
    return {"n": n, "net": mean, "gross": gm, "cost": float(cost.mean()), "t": t, "t_gross": tg,
            "p": R.norm_p_one_sided(t), "win": float((net > 0).mean()), "pf": pf,
            "hold_min": float(np.median(hold_min)), "mae50": float(np.percentile(mae, 50)),
            "mae90": float(np.percentile(mae, 90)), "years_pos": pos, "years_tot": tot}


def run(m1, verbose=True):
    rows = []
    for tf in TIMEFRAMES:
        t0 = time.time()
        bars = R.resample(m1, tf)
        n = len(bars["ts"])
        if n < 500:
            continue
        hp, lp = zigzag_levels(bars["bh"], bars["bl"])
        variants = break_variants(bars["bh"], bars["bl"], bars["bc"], hp, lp)
        for name, (up, dn) in variants.items():
            trades, n_both = simulate(up, dn, n)
            if len(trades) < MIN_TRADES:
                continue
            d, net, gross, cost, mae, hold, years = trade_results(trades, bars)
            for side, mk in (("合算", np.ones(len(d), bool)), ("買い", d == 1), ("売り", d == -1)):
                r = summarize(net[mk], gross[mk], cost[mk], mae[mk], hold[mk], years[mk])
                if r:
                    r.update({"tf": tf, "def": name, "side": side, "ambiguous_bars": n_both})
                    rows.append(r)
        if verbose:
            print(f"  {tf}分足: 完了 ({time.time() - t0:.0f}秒)", flush=True)
    return rows


COLS = ["tf", "def", "side", "n", "net", "gross", "cost", "t", "t_gross", "p", "win", "pf", "hold_min",
        "mae50", "mae90", "years_pos", "years_tot", "ambiguous_bars", "bh_pass"]


def save_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for r in rows:
            w.writerow([round(r[c], 4) if isinstance(r.get(c), float) else r.get(c, "") for c in COLS])


def show(rows, title, k=15):
    print(f"\n{title}")
    print("足 | 定義 | 方向 | 取引数 | 平均損益(bps) | 中値の平均 | コスト | t | 勝率 | PF | 保有(分,中央値) | 年プラス | 最大逆行(中央/90%)")
    for r in rows[:k]:
        print(f"{r['tf']}分 | {r['def']} | {r['side']} | {r['n']} | {r['net']:.1f} | {r['gross']:.1f} | "
              f"{r['cost']:.1f} | {r['t']:.2f} | {r['win'] * 100:.0f}% | {r['pf']:.2f} | {r['hold_min']:.0f} | "
              f"{r['years_pos']}/{r['years_tot']} | {r['mae50']:.0f}/{r['mae90']:.0f}")


def cmd_explore(a):
    con = sqlite3.connect(R.DB_PATH)
    m1 = R.load_1m(con, a.symbol, *R.EXPLORE)
    d0 = dt.datetime.fromtimestamp(int(m1["ts"][0]), R.UTC).date()
    d1 = dt.datetime.fromtimestamp(int(m1["ts"][-1]), R.UTC).date()
    print(f"[{a.symbol}] 探索期間のデータ: {d0}〜{d1} / 1分足 {len(m1['ts']):,}本", flush=True)
    rows = run(m1)
    main_rows = [r for r in rows if r["side"] == "合算"]
    flags = R.bh_flags(main_rows)
    for r, f in zip(main_rows, flags):
        r["bh_pass"] = int(f)
    rows.sort(key=lambda r: (r["side"] != "合算", -r["t"]))
    os.makedirs(R.OUT_DIR, exist_ok=True)
    save_csv(os.path.join(R.OUT_DIR, f"breakout_{a.symbol}.csv"), rows)
    main_rows.sort(key=lambda r: -r["t"])
    passed = [r for r in main_rows if r["bh_pass"] and r["net"] > 0]
    print(f"\n検証した組み合わせ(足×抜けの定義): {len(main_rows)} / "
          f"多重検定補正後も、コスト後の期待値がプラスと言えるもの: {len(passed)}")
    show(main_rows, "期待値のt値が高い順(合算。参考。補正前の見かけの強さ)")
    if passed:
        show(passed, "補正後も有意にプラスのもの")
    print("\n(全組み合わせは results/ のCSVに保存しました)")
    return 0


def cmd_detail(a):
    """1つの組み合わせの売買を1回ずつ確認する(チャートと見比べて、急騰や長いレンジを拾えているかを確認するため)。"""
    con = sqlite3.connect(R.DB_PATH)
    m1 = R.load_1m(con, a.symbol, *R.EXPLORE)
    bars = R.resample(m1, a.tf)
    n = len(bars["ts"])
    hp, lp = zigzag_levels(bars["bh"], bars["bl"])
    variants = break_variants(bars["bh"], bars["bl"], bars["bc"], hp, lp)
    if a.defn not in variants:
        raise SystemExit(f"定義名が違います。使えるもの: {', '.join(variants)}")
    up, dn = variants[a.defn]
    trades, _ = simulate(up, dn, n)
    if not trades:
        raise SystemExit("売買がありませんでした")
    d, net, gross, cost, mae, hold, years = trade_results(trades, bars)
    en = np.array([t[1] for t in trades])
    ex = np.array([t[2] for t in trades])
    ao, bo = bars["ao"], bars["bo"]
    long_ = d == 1
    ep = np.where(long_, ao[en], bo[en])
    xp = np.where(long_, bo[ex], ao[ex])
    mfe = np.empty(len(trades))
    for k in range(len(trades)):
        lo, hi = en[k], ex[k]
        if long_[k]:
            mfe[k] = max(0.0, (bars["bh"][lo:hi].max() - ep[k]) / ep[k] * 1e4)
        else:
            mfe[k] = max(0.0, (ep[k] - bars["al"][lo:hi].min()) / ep[k] * 1e4)
    day = lambda i: dt.datetime.fromtimestamp(int(bars["ts"][i]), R.UTC).strftime("%Y-%m-%d %H:%M")
    print(f"[{a.symbol} {a.tf}分 {a.defn}] 売買 {len(trades)}回 / 損益の合計 {net.sum():.0f}bps / 平均 {net.mean():.1f}bps")
    print("年別: " + " ".join(f"{y}年 {net[years == y].sum():+.0f}bps({(years == y).sum()}回)" for y in np.unique(years)))
    order = np.argsort(-net)
    def line(k):
        return (f"{day(en[k])} {'買い' if long_[k] else '売り'} {ep[k]:.3f}→{xp[k]:.3f} "
                f"{hold[k] / 1440:.1f}日 損益{net[k]:+.0f} 最大含み益{mfe[k]:.0f} 最大逆行{mae[k]:.0f}")
    print("\n勝ち上位5回(日時はUTC / 損益と含み益・逆行はbps):")
    for k in order[:5]:
        print("  " + line(k))
    print("負け上位5回:")
    for k in order[::-1][:5]:
        print("  " + line(k))
    top5 = net[order[:5]].sum()
    print(f"\n勝ち上位5回の合計 {top5:.0f}bps(全体の合計 {net.sum():.0f}bps)")
    print(f"中央値: 損益 {np.median(net):.0f} / 最大含み益 {np.median(mfe):.0f} / 最大逆行 {np.median(mae):.0f} (bps)")
    print(f"最大含み益の合計 {mfe.sum():.0f}bps に対し、実際に得た損益(中値)の合計 {gross.sum():.0f}bps")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("explore")
    s.add_argument("--symbol", default="XAGUSD")
    s2 = sub.add_parser("detail")
    s2.add_argument("--symbol", default="XAGUSD")
    s2.add_argument("--tf", type=int, required=True)
    s2.add_argument("--defn", required=True)
    a = p.parse_args()
    sys.exit({"explore": cmd_explore, "detail": cmd_detail}[a.cmd](a))


if __name__ == "__main__":
    main()
