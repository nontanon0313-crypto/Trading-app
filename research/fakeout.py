#!/usr/bin/env python3
"""ダマシ(一時的に節目を抜けてすぐ戻る現象)の実態測定。段階A。

  python fakeout.py explore [--symbol XAGUSD]          # 探索期間(2021〜2023年)の実データ
  python fakeout.py explore --null [--symbol XAGUSD]   # 比較用: 同じ足の形をランダムに並べ替えたデータ

比較用(--null)について: 実データの1分足を1本ずつ(始値に対する終値・高値・安値の比率の組のまま)ランダムに並べ替え、
前の足の終値から順につなぎ直したデータで、同じ測定を行う。値動きの大きさの分布は実データと同じだが、
足と足の順序に意味がない。実データとの差が、「実際のチャートの構造」に由来する部分である。
(ランダムな値動きでも、ブレイク後に戻る現象は起きるため、実データだけを見ても判断できない)

比較用は2種類:
  順序ランダム: 足の順序をランダムにする。値動きの大きさの分布は同じだが、ボラティリティの塊・時間帯・方向の構造は全て消える。
  符号ランダム: 各足の上下の向きだけをランダムにする(足の大きさの並び=ボラティリティの塊と時間帯は実データのまま)。
    実データとの差は「方向の構造(勢い・戻りやすさ)」、順序ランダムとの差は「ボラティリティの塊」に由来する。

fractal: 下位足のブレイクが、上位足のトレンド(波動の定義による上昇・下降・レンジ)に左右されるかを測る。

sequence: ブレイクの順序構造を測る。
  - ダマシ = ブレイクの後、逆ブレイク(直前に確定した反対側の節目を抜ける)が先に起きた場合。
    本物 = 同じ方向の次のブレイク(新しく確定した節目を抜ける)が先に起きた場合。
  - 発散 = 逆ブレイクが繰り返され、上下に広がりながら往復する動き。
    ・逆ブレイクの連続: 逆ブレイクの後、さらに逆ブレイクが続く確率(1回目、2回目、3回目…)。
      各回の確率が同じなら、逆ブレイクは前の結果に左右されない(独立)。
    ・拡大の割合: 逆ブレイクが連続した往復のうち、同じ側の極値(高値は高値どうし、安値は安値どうし)が前より外側に広がった割合。
  - ブレイクの定義は、ヒゲ(少しでも抜けた)と実体(終値で抜けた)の2通り。

volatility: ダマシと本物を分ける特徴としての「ボラティリティの状態」。
  - 状態 = 直近の値動き / 長期の値動き(ATRの単純平均の比。既定は短期14本 / 長期100本。--short --long で変更可)。
    ブレイクの1本前までの値だけを使う。1より大きければ「直近のほうが大きい」、小さければ「直近のほうが小さい」。
  - 状態の区切りは、全ての足の比を小さい順に5等分した分位(Q1=最も小さい … Q5=最も大きい)。しきい値は仮置きしない。
  - 各状態でのダマシの割合(逆ブレイクが先の割合)を、実データと符号ランダムで並べて示す。

levels: 「特定の価格で止められる」(過去の高値・安値=サポート・レジスタンス)の検証。
  - 過去の高値・安値 = これまでに確定した節目(波動の38.2%の定義)。
  - 各節目の価格が、過去に確定した節目の価格と近い割合を測る(1,2,3,5,8,13,21,34回前の節目。同じ種類と反対の種類を分ける)。
    近さ = 価格差をATR14で割った値(0.25 / 0.5 / 1.0 の3通りを全て並べる)。ATRは確定する1本前までの値。
  - 同じ価格帯で反転を繰り返す(止められる)なら、遠い過去(kが大きい)の節目とも近くなり、
    実データのほうが符号ランダムより割合が高くなる。
  - 注意: 「特定の価格」だけでなく、レンジ相場(一定の幅で上下する動き)でも割合が高くなる。この検証では両者を区別できない。

strong: 同じ価格に何度も反転した水準(強い節目)が存在するかの検証。時間は区切らない(全期間を使う)。
  - 価格を等間隔の帯に区切り、帯ごとに「反転した回数(確定した節目の数)」と「価格が滞在した時間(終値の本数)」を数える。
  - 各帯の反転の期待回数は、近傍の帯(両側10帯、その帯自身は除く)の反転回数と滞在時間から求める(ポアソン分布)。
    狭い価格帯に反転が集中していれば、期待より外れる(ばらつき指数 > 1)。全体の価格の動きには左右されない。
  - 帯の幅は、その時間足のATR14の中央値の0.25 / 0.5 / 1.0倍(全て並べる)。実データと符号ランダムで比べる。
  - 強い価格帯 = 期待回数に対して反転が有意に多い帯(z>=3)。そこにある節目の割合も示す。

strongbreak: 強い価格帯にある節目でブレイクしたときの、ダマシの割合の検証。
  - 価格帯の強さは、ブレイクの時点までに確定した節目と、それまでの滞在時間だけから求める(未来の情報は使わない)。
    期待回数は、strongと同じく、近傍の帯の反転回数と滞在時間から求め、ブレイクした節目そのものは数えない。
  - 強い帯 = その時点で、期待より反転が有意に多い帯(z>=3)。ブレイクした節目が、強い帯にあったかどうかで、ダマシの割合を比べる。
  - 帯の幅は、その時間足のATR14の中央値の0.25 / 0.5 / 1.0倍(全て並べる)。実データと符号ランダムで比べる。

測るもの(仮置きの数値は使わない。測定の目盛りは全て並べて表示するだけ):
  - ブレイク: 直前に確定した節目(波動の38.2%の定義)を、高値・安値が少しでも超えた最初の足。節目ごとに1回。
  - 戻る: 終値が節目の内側(上方ブレイクなら節目以下)に戻ること。別に「ヒゲで触れて戻る」も測る。
  - 打ち切り: 逆方向のブレイク(直前に確定した反対側の節目を抜けた)が起きた足、またはデータの終わり。
  - 深さ: 戻るまでに、節目を超えた最大幅(戻らなかったものは、打ち切りまでの最大の伸び)。
    単位は4通り: 価格に対する割合(%) / ブレイクした波の値幅に対する割合 / ATR(14本)の倍率 / ATR(100本)の倍率。
    ATRはブレイクの1本前までの単純平均(未来の情報は使わない)。
  - 戻った後の反転幅: 戻った足から打ち切りまでに、節目の反対側へ進んだ最大幅(同じ4通りの単位)。
"""
import argparse
import csv
import datetime as dt
import os
import sqlite3
import sys
import time

import numpy as np

import breakout as B
import env
import research as R

GRID = (0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89)  # 戻るまでの本数の目盛り(表示用)
UNITS = ("割合%", "波の値幅", "ATR14", "ATR100")


def atr_sma(h, l, c, n):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(h), np.nan)
    if len(h) >= n:
        cs = np.cumsum(np.insert(tr, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def analyze(h, l, c, hp, lp, hleg, lleg, hid, lid, atr14, atr100):
    """節目ごとの最初のブレイクを拾い、戻り・深さ・反転幅を測る。戻り値: 記録のリスト。
    記録 = (方向, 足の位置, 節目, 戻った本数(終値)または-1, 触れて戻った本数または-1,
            深さ(価格), 反転幅(価格,戻らなければ-1), 波の値幅, ATR14, ATR100)"""
    n = len(h)
    with np.errstate(invalid="ignore"):
        up_w = np.asarray(h > hp, dtype=bool)
        dn_w = np.asarray(l < lp, dtype=bool)
    up_idx = np.flatnonzero(up_w)
    dn_idx = np.flatnonzero(dn_w)
    recs = []
    for direction, brk, other, ids, lvl, leg in ((1, up_idx, dn_idx, hid, hp, hleg),
                                                (-1, dn_idx, up_idx, lid, lp, lleg)):
        done = set()
        for j in brk:
            key = int(ids[j])
            if key in done:
                continue
            done.add(key)
            level = lvl[j]
            p = np.searchsorted(other, j, side="right")
            cut = int(other[p]) if p < len(other) else n - 1
            if direction == 1:
                back = np.flatnonzero(c[j:cut + 1] <= level)
            else:
                back = np.flatnonzero(c[j:cut + 1] >= level)
            if len(back):
                r = j + int(back[0])
                ret = r - j
                if direction == 1:
                    depth = h[j:r + 1].max() - level
                    rev = max(0.0, level - l[r:cut + 1].min())
                else:
                    depth = level - l[j:r + 1].min()
                    rev = max(0.0, h[r:cut + 1].max() - level)
            else:
                ret = -1
                rev = -1.0
                depth = (h[j:cut + 1].max() - level) if direction == 1 else (level - l[j:cut + 1].min())
            if direction == 1:
                touch = np.flatnonzero(l[j + 1:cut + 1] <= level)
            else:
                touch = np.flatnonzero(h[j + 1:cut + 1] >= level)
            tk = int(touch[0]) + 1 if len(touch) else -1
            a14 = atr14[j - 1] if j >= 1 else np.nan
            a100 = atr100[j - 1] if j >= 1 else np.nan
            recs.append((direction, int(j), float(level), ret, tk, float(depth), float(rev),
                         float(leg[j]), float(a14), float(a100)))
    return recs


def to_units(value, level, leg, a14, a100):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.vstack([value / level * 100.0, value / leg, value / a14, value / a100])


def pct(x, q):
    x = x[~np.isnan(x)]
    return float(np.percentile(x, q)) if len(x) else float("nan")


def report(tf, recs):
    arr = np.array(recs, dtype=float)
    n = len(arr)
    ret = arr[:, 3]
    tk = arr[:, 4]
    out = [f"[{tf}分足] ブレイク {n}回(上方{int((arr[:, 0] == 1).sum())}/下方{int((arr[:, 0] == -1).sum())})"]
    cum = lambda v, ks: " ".join(f"{k}:{((v >= 0) & (v <= k)).mean() * 100:.0f}%" for k in ks)
    out.append("終値で戻る割合(本数以内): " + cum(ret, GRID) + f" 戻らず:{(ret < 0).mean() * 100:.0f}%")
    out.append("ヒゲで触れて戻る割合: " + cum(tk, GRID[1:]) + f" 触れず:{(tk < 0).mean() * 100:.0f}%")
    level, leg, a14, a100 = arr[:, 2], arr[:, 7], arr[:, 8], arr[:, 9]
    dep = to_units(arr[:, 5], level, leg, a14, a100)
    rev = to_units(np.where(arr[:, 6] >= 0, arr[:, 6], np.nan), level, leg, a14, a100)
    back = ret >= 0
    for name, mk, mat in (("深さ(戻ったもの)", back, dep), ("伸び(戻らなかったもの)", ~back, dep),
                          ("戻った後の反転幅", back, rev)):
        if mk.sum() == 0:
            continue
        cells = " | ".join(f"{u} {pct(mat[k][mk], 50):.2f}/{pct(mat[k][mk], 90):.2f}" for k, u in enumerate(UNITS))
        out.append(f"{name}(中央値/90%): {cells}")
    return out


COLS = ["tf", "dir", "time", "level", "ret_close", "ret_touch", "depth", "reversal", "leg", "atr14", "atr100"]


def shuffled_series(m1, seed=1):
    """1分足を1本ずつ(始値に対する終値・高値・安値の比率の組のまま)並べ替え、終値から順につなぎ直す。"""
    bo, bh, bl, bc = m1["bo"], m1["bh"], m1["bl"], m1["bc"]
    ratios = np.vstack([bc / bo, bh / bo, bl / bo])
    rng = np.random.default_rng(seed)
    ratios = ratios[:, rng.permutation(ratios.shape[1])]
    close = bc[0] * np.cumprod(ratios[0])
    opn = np.r_[bc[0], close[:-1]]
    out = {"ts": m1["ts"], "bo": opn, "bc": close, "bh": opn * ratios[1], "bl": opn * ratios[2]}
    for k in ("o", "h", "l", "c"):
        out["a" + k] = out["b" + k]
    return out


def signflip_series(m1, seed=2):
    """各足の上下の向きだけをランダムにする。足の大きさの並び(ボラティリティの塊・時間帯)は実データのまま。"""
    bo, bh, bl, bc = m1["bo"], m1["bh"], m1["bl"], m1["bc"]
    rc, rh, rl = np.log(bc / bo), np.log(bh / bo), np.log(bl / bo)
    rng = np.random.default_rng(seed)
    flip = rng.random(len(bo)) < 0.5
    rc2 = np.where(flip, -rc, rc)
    rh2 = np.where(flip, -rl, rh)
    rl2 = np.where(flip, -rh, rl)
    close = bc[0] * np.exp(np.cumsum(rc2))
    opn = np.r_[bc[0], close[:-1]]
    out = {"ts": m1["ts"], "bo": opn, "bc": close, "bh": opn * np.exp(rh2), "bl": opn * np.exp(rl2)}
    for k in ("o", "h", "l", "c"):
        out["a" + k] = out["b" + k]
    return out


def cmd_explore(a):
    con = sqlite3.connect(R.DB_PATH)
    m1 = R.load_1m(con, a.symbol, *R.EXPLORE)
    if a.null:
        m1 = shuffled_series(m1)
    d0 = dt.datetime.fromtimestamp(int(m1["ts"][0]), R.UTC).date()
    d1 = dt.datetime.fromtimestamp(int(m1["ts"][-1]), R.UTC).date()
    kind = "比較用(足の順序をランダムに並べ替えたデータ)" if a.null else "実データ"
    print(f"[{a.symbol}] {kind} 探索期間: {d0}〜{d1} / 1分足 {len(m1['ts']):,}本\n", flush=True)
    os.makedirs(R.OUT_DIR, exist_ok=True)
    path = os.path.join(R.OUT_DIR, f"fakeout_{a.symbol}{'_null' if a.null else ''}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for tf in B.TIMEFRAMES:
            t0 = time.time()
            bars = R.resample(m1, tf)
            if len(bars["ts"]) < 500:
                continue
            h, l, c = bars["bh"], bars["bl"], bars["bc"]
            hp, lp, hleg, lleg, hid, lid = B.zigzag_full(h, l)
            recs = analyze(h, l, c, hp, lp, hleg, lleg, hid, lid, atr_sma(h, l, c, 14), atr_sma(h, l, c, 100))
            if not recs:
                continue
            for r in recs:
                w.writerow([tf, r[0], int(bars["ts"][r[1]]), round(r[2], 5), r[3], r[4], round(r[5], 5),
                            round(r[6], 5), round(r[7], 5), round(r[8], 5), round(r[9], 5)])
            print("\n".join(report(tf, recs)), flush=True)
            print(f"   ({time.time() - t0:.0f}秒)\n", flush=True)
    print(f"(全ての記録は {path} に保存しました)")
    return 0


def summary_row(recs):
    arr = np.array(recs, dtype=float)
    ret = arr[:, 3]
    back = ret >= 0
    within = lambda k: ((ret >= 0) & (ret <= k)).mean() * 100
    dep = to_units(arr[:, 5], arr[:, 2], arr[:, 7], arr[:, 8], arr[:, 9])[2]
    rev = to_units(np.where(arr[:, 6] >= 0, arr[:, 6], np.nan), arr[:, 2], arr[:, 7], arr[:, 8], arr[:, 9])[2]
    return {"n": len(arr), "r0": within(0), "r1": within(1), "r3": within(3), "none": (ret < 0).mean() * 100,
            "d50": pct(dep[back], 50), "d90": pct(dep[back], 90), "e50": pct(dep[~back], 50),
            "e90": pct(dep[~back], 90), "v50": pct(rev[back], 50), "v90": pct(rev[back], 90)}


def cmd_compare(a):
    """実データと比較用データの主な指標を、足ごとに並べて表示する(単位はATR14の倍率)。"""
    con = sqlite3.connect(R.DB_PATH)
    m_real = R.load_1m(con, a.symbol, *R.EXPLORE)
    sets = (("実データ", m_real), ("順序ランダム", shuffled_series(m_real)), ("符号ランダム", signflip_series(m_real)))
    print("足 | データ | 回数 | 同じ足で戻る% | 1本以内% | 3本以内% | 戻らず% | 深さ(戻った:中央/90%) | 伸び(戻らず:中央/90%) | 反転幅(中央/90%)")
    for tf in B.TIMEFRAMES:
        for label, m1 in sets:
            bars = R.resample(m1, tf)
            if len(bars["ts"]) < 500:
                continue
            h, l, c = bars["bh"], bars["bl"], bars["bc"]
            hp, lp, hleg, lleg, hid, lid = B.zigzag_full(h, l)
            recs = analyze(h, l, c, hp, lp, hleg, lleg, hid, lid, atr_sma(h, l, c, 14), atr_sma(h, l, c, 100))
            if not recs:
                continue
            r = summary_row(recs)
            print(f"{tf}分 | {label} | {r['n']} | {r['r0']:.0f} | {r['r1']:.0f} | {r['r3']:.0f} | {r['none']:.0f} | "
                  f"{r['d50']:.2f}/{r['d90']:.2f} | {r['e50']:.2f}/{r['e90']:.2f} | {r['v50']:.2f}/{r['v90']:.2f}", flush=True)
    return 0


def prepare(m1):
    """足ごとの(足データ, ブレイクの記録, 上位足として使うトレンド状態)"""
    out = {}
    for tf in B.TIMEFRAMES:
        bars = R.resample(m1, tf)
        if len(bars["ts"]) < 500:
            continue
        h, l, c = bars["bh"], bars["bl"], bars["bc"]
        hp, lp, hleg, lleg, hid, lid = B.zigzag_full(h, l)
        recs = analyze(h, l, c, hp, lp, hleg, lleg, hid, lid, atr_sma(h, l, c, 14), atr_sma(h, l, c, 100))
        if recs:
            out[tf] = (bars, np.array(recs, dtype=float), env.zigzag_trend(h, l))
    return out


def fractal_cells(prep):
    """{(下位足, 上位足): {区分: (回数, 戻らず%, 1本以内%)}}。区分=上位足のトレンドに対する下位足ブレイクの向き。"""
    res = {}
    tfs = sorted(prep)
    for low in tfs:
        bars_l, arr, _ = prep[low]
        d = arr[:, 0]
        j = arr[:, 1].astype(int)
        ret = arr[:, 3]
        for high in tfs:
            if high <= low:
                continue
            bars_h, _, st_h = prep[high]
            s = env.map_to_lower(bars_l["ts"], low * 60, bars_h["ts"], high * 60, st_h)[j]
            cats = {"順張り": (s != 0) & (d == s), "逆張り": (s != 0) & (d == -s), "レンジ": s == 0}
            cell = {}
            for name, mk in cats.items():
                n = int(mk.sum())
                cell[name] = (n, float((ret[mk] < 0).mean() * 100) if n else float("nan"),
                              float(((ret[mk] >= 0) & (ret[mk] <= 1)).mean() * 100) if n else float("nan"))
            res[(low, high)] = cell
    return res


def cmd_fractal(a):
    """下位足のブレイクが、上位足のトレンドに左右されるか。表示は「実データ(符号ランダム)」。"""
    con = sqlite3.connect(R.DB_PATH)
    m_real = R.load_1m(con, a.symbol, *R.EXPLORE)
    real = fractal_cells(prepare(m_real))
    null = fractal_cells(prepare(signflip_series(m_real)))
    print("下位足←上位足 | 順張り(上位足のトレンドと同じ向きのブレイク) | 逆張り | 上位足がレンジ | 戻らず%の差(順張り-逆張り)")
    print("各区分: 回数 戻らず% 1本以内%  ※括弧内は符号ランダム(方向の構造を消した比較用)")
    for key in sorted(real):
        low, high = key
        cells = []
        for name in ("順張り", "逆張り", "レンジ"):
            n, nn, r1 = real[key][name]
            _, nnn, r1n = null[key][name]
            cells.append(f"{n}回 {nn:.0f}%({nnn:.0f}%) {r1:.0f}%({r1n:.0f}%)")
        diff = real[key]["順張り"][1] - real[key]["逆張り"][1]
        diffn = null[key]["順張り"][1] - null[key]["逆張り"][1]
        print(f"{low}分←{high}分 | " + " | ".join(cells) + f" | {diff:+.1f}pt({diffn:+.1f}pt)", flush=True)
    return 0


def break_events(h, l, c, hp, lp, hid, lid, mode):
    """節目ごとの最初のブレイクを時間順に並べる。戻り値: ([(足の位置, 方向)], 判断できない足の数)。
    同じ足で上下の両方が成立した足は、順序が判断できないため除く。"""
    with np.errstate(invalid="ignore"):
        if mode == "ヒゲ":
            up = np.asarray(h > hp, dtype=bool)
            dn = np.asarray(l < lp, dtype=bool)
        else:
            up = np.asarray(c > hp, dtype=bool)
            dn = np.asarray(c < lp, dtype=bool)
    both = up & dn
    up = up & ~both
    dn = dn & ~both
    ev = []
    for direction, mk, ids in ((1, up, hid), (-1, dn, lid)):
        seen = set()
        for j in np.flatnonzero(mk):
            k = int(ids[j])
            if k in seen:
                continue
            seen.add(k)
            ev.append((int(j), direction))
    ev.sort()
    return ev, int(both.sum())


def seq_stats(ev, h, l):
    """ブレイクの順序構造。戻り値: ダマシの割合、逆ブレイクの連続確率(1回目・2回目・3回目・4回目)、拡大の割合など。"""
    m = len(ev)
    if m < 8:
        return None
    t = np.array([e[0] for e in ev])
    d = np.array([e[1] for e in ev])
    flip = d[1:] != d[:-1]                       # flip[k]: k番目のブレイクの次が逆ブレイク
    run = np.zeros(m, dtype=int)                 # run[k]: k番目の後に続く逆ブレイクの連続回数
    for k in range(m - 2, -1, -1):
        run[k] = 1 + run[k + 1] if flip[k] else 0
    r = run[:m - 1]                              # 最後のブレイクは次が分からないので除く
    res = {"events": m, "dama": float((r >= 1).mean() * 100)}
    for i in (2, 3, 4):
        base = r >= i - 1
        res[f"c{i}"] = float((r[base] >= i).mean() * 100) if base.sum() >= 20 else float("nan")
        res[f"n{i}"] = int(base.sum())
    # 局面ごとの極値(そのブレイクから次のブレイクの直前まで)
    ext = np.empty(m - 1)
    for k in range(m - 1):
        a, b = t[k], t[k + 1]
        ext[k] = h[a:b].max() if d[k] == 1 else l[a:b].min()
    exp = tot = 0
    for k in range(m - 3):
        if flip[k] and flip[k + 1]:
            tot += 1
            exp += int(ext[k + 2] > ext[k]) if d[k] == 1 else int(ext[k + 2] < ext[k])
    res["expand"] = float(exp / tot * 100) if tot >= 20 else float("nan")
    res["expand_n"] = tot
    return res


def cmd_sequence(a):
    """ブレイクの順序構造を、実データと符号ランダム(方向の構造を消した比較用)で並べて表示する。"""
    con = sqlite3.connect(R.DB_PATH)
    m_real = R.load_1m(con, a.symbol, *R.EXPLORE)
    sets = (("実データ", m_real), ("符号ランダム", signflip_series(m_real)))
    print("足 | 定義 | データ | ブレイク数 | ダマシ%(逆ブレイクが先) | 逆ブレイクが続く確率%: 2回目(回数) | 3回目 | 4回目 | 拡大%(回数)")
    for tf in B.TIMEFRAMES:
        for label, m1 in sets:
            bars = R.resample(m1, tf)
            if len(bars["ts"]) < 500:
                continue
            h, l, c = bars["bh"], bars["bl"], bars["bc"]
            hp, lp, _, _, hid, lid = B.zigzag_full(h, l)
            for mode in ("ヒゲ", "実体"):
                ev, _ = break_events(h, l, c, hp, lp, hid, lid, mode)
                r = seq_stats(ev, h, l)
                if not r:
                    continue
                print(f"{tf}分 | {mode} | {label} | {r['events']} | {r['dama']:.1f} | "
                      f"{r['c2']:.1f}({r['n2']}) | {r['c3']:.1f}({r['n3']}) | {r['c4']:.1f} | "
                      f"{r['expand']:.1f}({r['expand_n']})", flush=True)
    return 0


def vol_ratio(h, l, c, short, long):
    a_s = atr_sma(h, l, c, short)
    a_l = atr_sma(h, l, c, long)
    with np.errstate(invalid="ignore", divide="ignore"):
        return a_s / a_l


def vol_table(ev, ratio, nb=5):
    """ブレイクの直前の足(1本前)までの比で状態を分け、各状態のダマシの割合を返す。
    戻り値: (境界のリスト, [(状態の番号, 回数, ダマシ%)], 最大と最小の状態の差のz値)"""
    m = len(ev)
    t = np.array([e[0] for e in ev])
    d = np.array([e[1] for e in ev])
    flip = (d[1:] != d[:-1])
    j = t[:m - 1]
    ok = j >= 1
    r = np.full(m - 1, np.nan)
    r[ok] = ratio[j[ok] - 1]
    cuts = np.nanpercentile(ratio, np.linspace(0, 100, nb + 1)[1:-1])
    out = []
    for b in range(nb):
        lo = -np.inf if b == 0 else cuts[b - 1]
        hi = np.inf if b == nb - 1 else cuts[b]
        mk = ~np.isnan(r) & (r >= lo) & (r < hi) if b < nb - 1 else ~np.isnan(r) & (r >= lo)
        n = int(mk.sum())
        out.append((b + 1, n, float(flip[mk].mean() * 100) if n >= 30 else float("nan")))
    ps = [(n, p) for _, n, p in out]
    z = float("nan")
    if ps[0][0] >= 30 and ps[-1][0] >= 30:
        p1, p5 = ps[0][1] / 100, ps[-1][1] / 100
        se = np.sqrt(p1 * (1 - p1) / ps[0][0] + p5 * (1 - p5) / ps[-1][0])
        z = (p5 - p1) / se if se > 0 else float("nan")
    return cuts, out, float(z)


def cmd_volatility(a):
    """ボラティリティの状態ごとのダマシの割合。実データと符号ランダムを並べて表示する。"""
    con = sqlite3.connect(R.DB_PATH)
    m_real = R.load_1m(con, a.symbol, *R.EXPLORE)
    sets = (("実データ", m_real), ("符号ランダム", signflip_series(m_real)))
    print(f"状態=ATR{a.short}/ATR{a.long}を5等分(Q1=直近の値動きが最も小さい … Q5=最も大きい)")
    print("足 | 定義 | データ | Q1 | Q2 | Q3 | Q4 | Q5 のダマシ%(逆ブレイクが先) | Q5-Q1の差(z値) | 各状態の回数の最小")
    for tf in B.TIMEFRAMES:
        for label, m1 in sets:
            bars = R.resample(m1, tf)
            if len(bars["ts"]) < 500:
                continue
            h, l, c = bars["bh"], bars["bl"], bars["bc"]
            hp, lp, _, _, hid, lid = B.zigzag_full(h, l)
            ratio = vol_ratio(h, l, c, a.short, a.long)
            for mode in ("ヒゲ", "実体"):
                ev, _ = break_events(h, l, c, hp, lp, hid, lid, mode)
                if len(ev) < 200:
                    continue
                cuts, rows, z = vol_table(ev, ratio)
                cells = " | ".join(f"{p:.1f}" for _, _, p in rows)
                diff = rows[-1][2] - rows[0][2]
                print(f"{tf}分 | {mode} | {label} | {cells} | {diff:+.1f}pt (z={z:+.1f}) | {min(n for _, n, _ in rows)}",
                      flush=True)
                if label == "実データ" and mode == "ヒゲ":
                    print("    比の区切り(実データ): " + " / ".join(f"{x:.2f}" for x in cuts), flush=True)
    return 0


def zigzag_pivots(h, l, ratio=B.RATIO):
    """確定した節目の一覧(確定した足の位置, 価格, 種類 +1=高値 -1=安値)。zigzag_fullと同じ判定。"""
    n = len(h)
    conf, price, kind = [], [], []
    if n:
        d = 1
        start = l[0]
        ext = h[0]
        for i in range(1, n):
            if d == 1:
                if h[i] > ext:
                    ext = h[i]
                if l[i] <= ext - ratio * (ext - start):
                    conf.append(i)
                    price.append(ext)
                    kind.append(1)
                    d = -1
                    start = ext
                    ext = l[i]
            else:
                if l[i] < ext:
                    ext = l[i]
                if h[i] >= ext + ratio * (start - ext):
                    conf.append(i)
                    price.append(ext)
                    kind.append(-1)
                    d = 1
                    start = ext
                    ext = h[i]
    return np.array(conf, dtype=np.int64), np.array(price, dtype=float), np.array(kind, dtype=np.int64)


STEPS = (1, 2, 3, 5, 8, 13, 21, 34)       # 何個前の節目と比べるか(目盛り。全て表示する)
EPS_GRID = (0.25, 0.5, 1.0)               # 近さの目盛り(ATR14の倍率。全て表示する)
# 節目は高値と安値が交互に確定する。同じ種類(高値と高値、安値と安値)は2m個前、反対の種類は2m+1個前。
SAME_LAGS = tuple(2 * m for m in STEPS)
CROSS_LAGS = tuple(2 * m + 1 for m in STEPS)


def pair_fractions(pc, pp, atr):
    """節目の価格が、k個前の節目の価格と近い割合%。{(k, 近さの番号): 割合%}。
    近さ = 価格差 / ATR14(新しい節目が確定する1本前の値)。"""
    out = {}
    scale = atr[pc - 1]
    for k in SAME_LAGS + CROSS_LAGS:
        if len(pp) <= k + 50:
            continue
        sc = scale[k:]
        with np.errstate(divide="ignore", invalid="ignore"):
            diff = np.abs(pp[k:] - pp[:-k]) / sc
        diff[~(sc > 0)] = np.nan          # ATRが0(値動きのない足)の節目は除く
        v = ~np.isnan(diff)
        for e, eps in enumerate(EPS_GRID):
            out[(k, e)] = float((diff[v] <= eps).mean() * 100)
    return out


def level_pair_tables(m1, tfs):
    res = {}
    for tf in tfs:
        bars = R.resample(m1, tf)
        if len(bars["ts"]) < 500:
            continue
        h, l, c = bars["bh"], bars["bl"], bars["bc"]
        pc, pp, _ = zigzag_pivots(h, l)
        if len(pc) < 200:
            continue
        res[tf] = (len(pc), pair_fractions(pc, pp, atr_sma(h, l, c, 14)))
    return res


def cmd_levels(a):
    """節目の価格が、過去の節目の価格とどれだけ近いかを、実データと符号ランダムで並べる。"""
    tfs = [int(x) for x in a.tfs.split(",")]
    con = sqlite3.connect(R.DB_PATH)
    m_real = R.load_1m(con, a.symbol, *R.EXPLORE)
    real = level_pair_tables(m_real, tfs)
    null = level_pair_tables(signflip_series(m_real), tfs)
    print("節目の価格が、過去の節目の価格と近い割合%(実データ / 符号ランダム)。近さ=価格差÷ATR14")
    print(f"同じ種類(高値と高値・安値と安値)は {STEPS} 回前の同じ種類の節目、反対の種類(高値と安値)は同じ回数+1個前の節目と比べる")
    for tf in tfs:
        if tf not in real or tf not in null:
            continue
        print(f"\n[{tf}分足] 節目 {real[tf][0]}個")
        for name, lags in (("同じ種類", SAME_LAGS), ("反対の種類", CROSS_LAGS)):
            print(f"  {name}: " + " | ".join(f"{m}回前" for m in STEPS))
            for e, eps in enumerate(EPS_GRID):
                cells = []
                for k in lags:
                    if (k, e) in real[tf][1] and (k, e) in null[tf][1]:
                        cells.append(f"{real[tf][1][(k, e)]:.1f}/{null[tf][1][(k, e)]:.1f}")
                    else:
                        cells.append("-")
                print(f"    近さ{eps}: " + " | ".join(cells), flush=True)
    return 0


BIN_GRID = (0.25, 0.5, 1.0)   # 価格帯の幅(その時間足のATR14の中央値に対する倍率。全て表示する)


NEIGHBOR_BINS = 10   # 近傍の帯の数(各帯の期待回数を、両側のこの数の帯から求める)


def dispersion(bars, pp, width):
    """価格帯ごとの反転回数が、「近傍の帯の反転回数と滞在時間」から期待される回数(ポアソン)より、どれだけ外れるか。
    各帯の期待回数 = (近傍の帯の反転回数の合計) × (その帯の滞在時間) / (近傍の帯の滞在時間の合計)。その帯自身は含めない。
    全体的な価格の動き(ある価格帯に長く滞在した等)に左右されず、狭い価格帯への集中だけを見る。
    戻り値: (ばらつき指数, z値, 強い帯の数, 強い帯にある節目の割合%, 使った帯の数)。指数は集中がなければ約1。"""
    c = bars["bc"]
    lo = min(c.min(), pp.min())
    hi = max(c.max(), pp.max())
    nb = int(np.ceil((hi - lo) / width)) + 1
    W = NEIGHBOR_BINS
    if nb < 4 * W:
        return None
    edges = lo + width * np.arange(nb + 1)
    occ = np.histogram(c, bins=edges)[0].astype(float)
    piv = np.histogram(pp, bins=edges)[0].astype(float)
    cp = np.concatenate([[0.0], np.cumsum(piv)])
    co = np.concatenate([[0.0], np.cumsum(occ)])
    idx = np.arange(nb)
    left = np.maximum(idx - W, 0)
    right = np.minimum(idx + W + 1, nb)
    n_win = cp[right] - cp[left] - piv
    o_win = co[right] - co[left] - occ
    with np.errstate(divide="ignore", invalid="ignore"):
        exp = n_win * occ / o_win
    use = np.isfinite(exp) & (exp >= 3)
    if use.sum() < 20:
        return None
    z = (piv[use] - exp[use]) / np.sqrt(exp[use])
    d = float((z ** 2).sum())
    df = int(use.sum())
    zz = (d - df) / np.sqrt(2 * df)
    zall = np.full(nb, np.nan)
    zall[use] = z
    strong = use & (np.nan_to_num(zall, nan=0.0) >= 3)
    return d / df, float(zz), int(strong.sum()), float(piv[strong].sum() / piv.sum() * 100), int(use.sum())


def cmd_strong(a):
    tfs = [int(x) for x in a.tfs.split(",")]
    con = sqlite3.connect(R.DB_PATH)
    m_real = R.load_1m(con, a.symbol, *R.EXPLORE)
    sets = (("実データ", m_real), ("符号ランダム", signflip_series(m_real)))
    print("価格帯ごとの反転回数のばらつき指数(滞在時間から期待されるばらつき=1。大きいほど特定の価格帯に反転が集中)")
    print("足 | 帯の幅(ATR14中央値の倍率) | データ | ばらつき指数(z値) | 強い帯の数 | 強い帯にある節目の割合% | 使った帯の数")
    for tf in tfs:
        for label, m1 in sets:
            bars = R.resample(m1, tf)
            if len(bars["ts"]) < 500:
                continue
            h, l, c = bars["bh"], bars["bl"], bars["bc"]
            pc, pp, _ = zigzag_pivots(h, l)
            if len(pc) < 200:
                continue
            med = float(np.nanmedian(atr_sma(h, l, c, 14)))
            for mult in BIN_GRID:
                r = dispersion(bars, pp, mult * med)
                if r is None:
                    continue
                print(f"{tf}分 | {mult} | {label} | {r[0]:.2f}(z={r[1]:+.1f}) | {r[2]} | {r[3]:.1f} | {r[4]}", flush=True)
    return 0


def causal_band_z(bars, pc, pp, j_arr, level_prices, width):
    """ブレイクごとに、その時点までのデータだけで求めた、節目がある価格帯の強さ(z値)。判定できない場合はNaN。"""
    c = bars["bc"]
    lo = min(c.min(), pp.min())
    hi = max(c.max(), pp.max())
    nb = int(np.ceil((hi - lo) / width)) + 1
    W = NEIGHBOR_BINS
    occ = np.zeros(nb)
    piv = np.zeros(nb)
    cb = np.clip(((c - lo) / width).astype(np.int64), 0, nb - 1)
    pb = np.clip(((pp - lo) / width).astype(np.int64), 0, nb - 1)
    lb = np.clip(((level_prices - lo) / width).astype(np.int64), 0, nb - 1)
    z = np.full(len(j_arr), np.nan)
    ci = pi = 0
    npv = len(pc)
    for k in range(len(j_arr)):
        j = j_arr[k]
        while ci < j:                       # jより前の足の終値だけを数える
            occ[cb[ci]] += 1
            ci += 1
        while pi < npv and pc[pi] < j:      # jより前に確定した節目だけを数える
            piv[pb[pi]] += 1
            pi += 1
        b = lb[k]
        l0, r0 = max(b - W, 0), min(b + W + 1, nb)
        o_win = occ[l0:r0].sum() - occ[b]
        if o_win <= 0:
            continue
        n_win = piv[l0:r0].sum() - piv[b]
        e = n_win * occ[b] / o_win
        if e < 3:
            continue
        z[k] = (piv[b] - 1 - e) / np.sqrt(e)   # ブレイクした節目そのものを除く
    return z


def strongbreak_tables(m1, tfs):
    """{足: {(定義, 幅の番号): (強い帯の回数, ダマシ%, それ以外の回数, ダマシ%, 判定不能の回数, 差のz値)}}"""
    res = {}
    for tf in tfs:
        bars = R.resample(m1, tf)
        if len(bars["ts"]) < 500:
            continue
        h, l, c = bars["bh"], bars["bl"], bars["bc"]
        hp, lp, _, _, hid, lid = B.zigzag_full(h, l)
        pc, pp, _ = zigzag_pivots(h, l)
        if len(pc) < 200:
            continue
        med = float(np.nanmedian(atr_sma(h, l, c, 14)))
        tab = {}
        for mode in ("ヒゲ", "実体"):
            ev, _ = break_events(h, l, c, hp, lp, hid, lid, mode)
            if len(ev) < 200:
                continue
            j = np.array([e[0] for e in ev])
            d = np.array([e[1] for e in ev])
            level = np.where(d == 1, hp[j], lp[j])
            flip = (d[1:] != d[:-1])
            for wi, mult in enumerate(BIN_GRID):
                z = causal_band_z(bars, pc, pp, j, level, mult * med)[:-1]
                ok = ~np.isnan(z)
                strong = ok & (z >= 3)
                weak = ok & (z < 3)
                ns, nw = int(strong.sum()), int(weak.sum())
                if ns < 30 or nw < 30:
                    tab[(mode, wi)] = (ns, float("nan"), nw, float("nan"), int((~ok).sum()), float("nan"))
                    continue
                ps, pw = float(flip[strong].mean()), float(flip[weak].mean())
                se = np.sqrt(ps * (1 - ps) / ns + pw * (1 - pw) / nw)
                tab[(mode, wi)] = (ns, ps * 100, nw, pw * 100, int((~ok).sum()), (ps - pw) / se if se > 0 else float("nan"))
        if tab:
            res[tf] = tab
    return res


def cmd_strongbreak(a):
    tfs = [int(x) for x in a.tfs.split(",")]
    con = sqlite3.connect(R.DB_PATH)
    m_real = R.load_1m(con, a.symbol, *R.EXPLORE)
    real = strongbreak_tables(m_real, tfs)
    null = strongbreak_tables(signflip_series(m_real), tfs)
    print("強い価格帯(その時点までのデータで、期待より反転が有意に多い帯)にある節目でブレイクしたときの、ダマシ%(逆ブレイクが先)")
    print("足 | 定義 | 帯の幅(ATR14中央値の倍率) | データ | 強い帯: 回数 ダマシ% | それ以外: 回数 ダマシ% | 差(強い-それ以外) z値")
    for tf in tfs:
        if tf not in real or tf not in null:
            continue
        for mode in ("ヒゲ", "実体"):
            for wi, mult in enumerate(BIN_GRID):
                for label, tab in (("実データ", real), ("符号ランダム", null)):
                    t = tab[tf].get((mode, wi))
                    if t is None:
                        continue
                    ns, ps, nw, pw, nn, z = t
                    diff = ps - pw
                    print(f"{tf}分 | {mode} | {mult} | {label} | {ns} {ps:.1f} | {nw} {pw:.1f} | {diff:+.1f}pt (z={z:+.1f})", flush=True)
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("explore")
    s.add_argument("--symbol", default="XAGUSD")
    s.add_argument("--null", action="store_true")
    for name in ("compare", "fractal", "sequence", "volatility", "levels", "strong", "strongbreak"):
        s2 = sub.add_parser(name)
        s2.add_argument("--symbol", default="XAGUSD")
        if name in ("levels", "strong", "strongbreak"):
            s2.add_argument("--tfs", default="5,15,60,240,1440")
        if name == "volatility":
            s2.add_argument("--short", type=int, default=14)
            s2.add_argument("--long", type=int, default=100)
    a = p.parse_args()
    sys.exit({"explore": cmd_explore, "compare": cmd_compare, "fractal": cmd_fractal,
              "sequence": cmd_sequence, "volatility": cmd_volatility,
              "levels": cmd_levels, "strong": cmd_strong,
              "strongbreak": cmd_strongbreak}[a.cmd](a))


if __name__ == "__main__":
    main()
