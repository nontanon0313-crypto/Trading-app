#!/usr/bin/env python3
"""全銘柄をまとめた、ブレイク売買の検証(1時間足・4時間足・日足)。1時間足のデータ(fetch_hourly.py)を使う。

  python multi.py explore        # 探索期間(2021〜2023年)で、足×抜けの定義ごとに、全銘柄の売買をまとめて検証
  python multi.py confirm --tf 1440 --defn 維持1
                                 # 確認用の期間(2024〜2025年)で、探索で選んだ1つの候補だけを検証(1回だけ)

定義はbreakout.pyと同じ(波動38.2%の節目、ブレイクでエントリー、逆ブレイクで決済、損切りなし、
次の足の始値で約定、買いはask・売りはbid)。銘柄ごとの売買を、そのまま(bpsで)合わせる。
注意: 銘柄どうしは値動きが連動する(例: ドルストレートどうし)ため、合わせた回数ほどには独立でない。
      t値は、実際より大きめに出る。「プラスの銘柄数」と「銘柄別の平均」を、あわせて見る。
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

TFS = (60, 240, 1440)


def symbol_trades(m):
    """1銘柄の、(足, 定義)ごとの売買結果。{(tf, 定義): (net, gross, cost, mae, hold, years)}"""
    out = {}
    for tf in TFS:
        bars = R.resample(m, tf)
        n = len(bars["ts"])
        if n < 200:
            continue
        hp, lp = B.zigzag_levels(bars["bh"], bars["bl"])
        for name, (up, dn) in B.break_variants(bars["bh"], bars["bl"], bars["bc"], hp, lp).items():
            trades, _ = B.simulate(up, dn, n)
            if len(trades) < 3:
                continue
            d, net, gross, cost, mae, hold, years = B.trade_results(trades, bars)
            out[(tf, name)] = (net, gross, cost, mae, hold, years)
    return out


def load_symbols(con):
    try:
        return [r[0] for r in con.execute("SELECT DISTINCT symbol FROM h1 ORDER BY symbol")]
    except sqlite3.OperationalError:
        return []


def pool(per_symbol):
    """銘柄ごとの結果を、(足, 定義)ごとにまとめる。"""
    keys = sorted({k for r in per_symbol.values() for k in r})
    rows = []
    for key in keys:
        parts = {s: r[key] for s, r in per_symbol.items() if key in r}
        cat = [np.concatenate([p[i] for p in parts.values()]) for i in range(6)]
        s = B.summarize(cat[0], cat[1], cat[2], cat[3], cat[4], cat[5])
        if not s:
            continue
        means = {sym: float(p[0].mean()) for sym, p in parts.items() if len(p[0]) >= 5}
        s.update({"tf": key[0], "def": key[1], "pos_syms": sum(1 for v in means.values() if v > 0),
                  "n_syms": len(means), "means": means})
        rows.append(s)
    return rows


def cmd_explore(a):
    con = sqlite3.connect(R.DB_PATH)
    syms = load_symbols(con)
    if not syms:
        raise SystemExit("1時間足のデータがありません。先に fetch_hourly.py run を実行してください")
    per_symbol = {}
    for sym in syms:
        try:
            m = R.load_1m(con, sym, *R.EXPLORE, table="h1")
        except SystemExit:
            continue
        if len(m["ts"]) < 2000:
            continue
        d0 = dt.datetime.fromtimestamp(int(m["ts"][0]), R.UTC).date()
        d1 = dt.datetime.fromtimestamp(int(m["ts"][-1]), R.UTC).date()
        print(f"{sym}: {d0}〜{d1} / 1時間足 {len(m['ts']):,}本", flush=True)
        per_symbol[sym] = symbol_trades(m)
    rows = pool(per_symbol)
    flags = R.bh_flags(rows)
    for r, f in zip(rows, flags):
        r["bh_pass"] = int(f)
    rows.sort(key=lambda r: -r["t"])
    os.makedirs(R.OUT_DIR, exist_ok=True)
    path = os.path.join(R.OUT_DIR, "multi_explore.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tf", "def", "n", "net", "gross", "cost", "t", "p", "win", "pf", "years_pos", "years_tot",
                    "pos_syms", "n_syms", "bh_pass"])
        for r in rows:
            w.writerow([r["tf"], r["def"], r["n"], round(r["net"], 3), round(r["gross"], 3), round(r["cost"], 3),
                        round(r["t"], 3), round(r["p"], 5), round(r["win"], 3), round(r["pf"], 3),
                        r["years_pos"], r["years_tot"], r["pos_syms"], r["n_syms"], r["bh_pass"]])
    passed = [r for r in rows if r["bh_pass"] and r["net"] > 0]
    print(f"\n銘柄 {len(per_symbol)}個をまとめた検証: {len(rows)}通り(足×抜けの定義) / "
          f"多重検定補正後も、コスト後の期待値がプラスと言えるもの: {len(passed)}")
    print("\n足 | 定義 | 取引数 | 平均損益(bps) | 中値の平均 | コスト | t | 勝率 | PF | 年プラス | プラスの銘柄 | 銘柄別の平均(bps)")
    for r in rows[:15]:
        sm = " ".join(f"{k}:{v:+.0f}" for k, v in sorted(r["means"].items()))
        print(f"{r['tf']}分 | {r['def']} | {r['n']} | {r['net']:.1f} | {r['gross']:.1f} | {r['cost']:.1f} | {r['t']:.2f} | "
              f"{r['win'] * 100:.0f}% | {r['pf']:.2f} | {r['years_pos']}/{r['years_tot']} | {r['pos_syms']}/{r['n_syms']} | {sm}")
    print(f"\n(全組み合わせは {path} に保存しました)")
    return 0


PASS_RULE = "コスト後の平均がプラス、片側p値<0.05、プラスの銘柄が過半数、2024年・2025年ともプラス"


def cmd_confirm(a):
    """確認用の期間で、探索で選んだ1つの候補だけを検証する。合格基準は、結果を見る前に固定している。
    状態をそろえるため、探索期間の前から価格を読み込み、確認用の期間にエントリーした売買だけを数える。"""
    con = sqlite3.connect(R.DB_PATH)
    syms = load_symbols(con)
    if not syms:
        raise SystemExit("1時間足のデータがありません")
    t_start, t_end = R.CONFIRM
    per = {}
    print(f"候補: {a.tf}分足・{a.defn} / 確認用の期間: 2024-01-01〜2025-12-31 / 合格基準: {PASS_RULE}\n")
    for sym in syms:
        try:
            m = R.load_1m(con, sym, R.EXPLORE[0], t_end, table="h1")
        except SystemExit:
            continue
        bars = R.resample(m, a.tf)
        n = len(bars["ts"])
        hp, lp = B.zigzag_levels(bars["bh"], bars["bl"])
        variants = B.break_variants(bars["bh"], bars["bl"], bars["bc"], hp, lp)
        if a.defn not in variants:
            raise SystemExit(f"定義名が違います。使えるもの: {', '.join(variants)}")
        up, dn = variants[a.defn]
        trades, _ = B.simulate(up, dn, n)
        trades = [t for t in trades if bars["ts"][t[1]] >= t_start]
        n_bars = int((bars["ts"] >= t_start).sum())
        if len(trades) < 3:
            print(f"{sym}: 売買が少なすぎます({len(trades)}回)")
            continue
        d, net, gross, cost, mae, hold, years = B.trade_results(trades, bars)
        per[sym] = (net, gross, cost, mae, hold, years)
        print(f"{sym}: 確認用の期間の足 {n_bars}本 / 売買 {len(trades)}回", flush=True)
    cat = [np.concatenate([p[i] for p in per.values()]) for i in range(6)]
    s = B.summarize(*cat)
    if not s:
        raise SystemExit("売買が少なすぎて、検証できません")
    pos_syms = sum(1 for p in per.values() if p[0].mean() > 0)
    yrs = cat[5]
    y_means = {int(y): float(cat[0][yrs == y].mean()) for y in np.unique(yrs)}
    print(f"\n全銘柄をまとめた結果: 売買 {s['n']}回 / コスト後の平均 {s['net']:+.1f}bps / 中値の平均 {s['gross']:+.1f}bps / "
          f"コスト {s['cost']:.1f}bps")
    print(f"t値 {s['t']:+.2f} / 片側p値 {s['p']:.4f} / 勝率 {s['win'] * 100:.0f}% / PF {s['pf']:.2f}")
    print("年ごとの平均: " + " ".join(f"{y}年 {v:+.1f}bps({int((yrs == y).sum())}回)" for y, v in sorted(y_means.items())))
    print("銘柄ごとの平均: " + " ".join(f"{k}:{v[0].mean():+.0f}({len(v[0])}回)" for k, v in sorted(per.items())))
    print(f"プラスの銘柄: {pos_syms}/{len(per)}")
    ok = (s["net"] > 0 and s["p"] < 0.05 and pos_syms > len(per) / 2 and all(v > 0 for v in y_means.values())
          and len(y_means) >= 2)
    print("\n判定: " + ("合格(確認用の期間でも、基準を満たした)" if ok else "不合格(基準を満たさなかった)"))
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("explore")
    c = sub.add_parser("confirm")
    c.add_argument("--tf", type=int, required=True)
    c.add_argument("--defn", required=True)
    a = p.parse_args()
    sys.exit({"explore": cmd_explore, "confirm": cmd_confirm}[a.cmd](a))


if __name__ == "__main__":
    main()
