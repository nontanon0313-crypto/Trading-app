"""検証するシグナル(グループ1)の定義。結果を見る前に固定する。

どのシグナルも「その足が確定した時点で分かる情報だけ」で判定する(未来の情報は使わない)。
エントリーは次の足の始値で行う(research.py側)。買い・売りの両方向を別々に評価する。
"""
import numpy as np

# ラウンドナンバーの刻み(銘柄ごと)
ROUND_STEP = {"XAGUSD": 5.0, "XAUUSD": 100.0, "USDJPY": 1.0, "EURJPY": 1.0,
              "GBPJPY": 1.0, "AUDJPY": 1.0, "EURUSD": 0.01, "GBPUSD": 0.01}
GAP_THRESHOLD = 0.0005   # ギャップ: 前の足の終値からの乖離率0.05%以上
GAP_MIN_SECONDS = 6 * 3600  # ギャップ: 足の間に6時間以上の休場があること


def prev(x):
    y = np.empty_like(x, dtype=float)
    y[0] = np.nan
    y[1:] = x[:-1]
    return y


def roll_max(x, n):
    from numpy.lib.stride_tricks import sliding_window_view as sw
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = sw(x, n).max(axis=1)
    return out


def roll_min(x, n):
    from numpy.lib.stride_tricks import sliding_window_view as sw
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = sw(x, n).min(axis=1)
    return out


def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rolling_std(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        x0 = x - x.mean()
        c1 = np.cumsum(np.insert(x0, 0, 0.0))
        c2 = np.cumsum(np.insert(x0 * x0, 0, 0.0))
        m = (c1[n:] - c1[:-n]) / n
        v = (c2[n:] - c2[:-n]) / n - m * m
        out[n - 1:] = np.sqrt(np.maximum(v, 0.0))
    return out


def ema(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    v = float(np.mean(x[:n]))
    out[n - 1] = v
    for i in range(n, len(x)):
        v += a * (x[i] - v)
        out[i] = v
    return out


def _b(x):
    """NaNを含む比較結果をFalseにそろえる"""
    return np.asarray(x, dtype=bool)


def _hold(brk, c, level, k, up):
    """実体で抜けた足jの基準を固定し、j+1〜j+k本の終値がすべて基準の外側なら、j+k本目に発生。"""
    nbar = len(c)
    out = np.zeros(nbar, dtype=bool)
    if nbar <= k:
        return out
    ok = brk[:nbar - k].copy()
    for t in range(1, k + 1):
        seg = c[t:nbar - k + t]
        ok &= _b(seg > level[:nbar - k]) if up else _b(seg < level[:nbar - k])
    out[k:] = ok
    return out


def g1_events(b, symbol, tf_seconds):
    """b: 足データ(ts,o,h,l,c: 売値側)。戻り値: {シグナル名: 真偽配列}"""
    o, h, l, c, ts = b["o"], b["h"], b["l"], b["c"], b["ts"]
    ev = {}
    with np.errstate(invalid="ignore"):
        # 高値・安値ブレイク(直前N本の高値/安値が基準)。抜けの定義を3通り検証する
        #   ヒゲ : 少しでも抜けたら(高値/安値が基準を超えた)
        #   実体 : 実体(終値)で抜けたら
        #   維持k: 実体で抜けた後、k本の間、終値が基準の外側に留まったら(k本目の確定時に発生)
        for n in (20, 50):
            hh = prev(roll_max(h, n))
            ll = prev(roll_min(l, n))
            ev[f"高値ブレイク{n}ヒゲ"] = _b(h > hh)
            ev[f"安値ブレイク{n}ヒゲ"] = _b(l < ll)
            up_body = _b(c > hh)
            dn_body = _b(c < ll)
            ev[f"高値ブレイク{n}実体"] = up_body
            ev[f"安値ブレイク{n}実体"] = dn_body
            for k in (1, 3, 5):
                ev[f"高値ブレイク{n}維持{k}"] = _hold(up_body, c, hh, k, up=True)
                ev[f"安値ブレイク{n}維持{k}"] = _hold(dn_body, c, ll, k, up=False)
        # 移動平均線: 上抜け/下抜け/タッチ
        pc = prev(c)
        for kind, fn in (("MA", sma), ("EMA", ema)):
            for n in (20, 50, 200):
                m = fn(c, n)
                pm = prev(m)
                ev[f"{kind}{n}上抜け"] = _b((pc <= pm) & (c > m))
                ev[f"{kind}{n}下抜け"] = _b((pc >= pm) & (c < m))
                ev[f"{kind}{n}タッチ"] = _b((l <= m) & (m <= h))
        # ボリンジャーバンド(20本): kσを終値が超えた
        m20 = sma(c, 20)
        sd20 = rolling_std(c, 20)
        for k in (1, 2, 3):
            up = m20 + k * sd20
            lo = m20 - k * sd20
            ev[f"BB{k}σ上抜け"] = _b((pc <= prev(up)) & (c > up))
            ev[f"BB{k}σ下抜け"] = _b((pc >= prev(lo)) & (c < lo))
        # プライスアクション
        body = np.abs(c - o)
        rng = h - l
        upw = h - np.maximum(o, c)
        low_w = np.minimum(o, c) - l
        po, ph, pl = prev(o), prev(h), prev(l)
        ev["陽線包み足"] = _b((c > o) & (po > pc) & (o <= pc) & (c >= po))
        ev["陰線包み足"] = _b((c < o) & (po < pc) & (o >= pc) & (c <= po))
        ev["ピンバー下ヒゲ"] = _b((rng > 0) & (low_w >= 2 * body) & (low_w >= 0.6 * rng))
        ev["ピンバー上ヒゲ"] = _b((rng > 0) & (upw >= 2 * body) & (upw >= 0.6 * rng))
        ev["インサイドバー"] = _b((h < ph) & (l > pl))
        ev["アウトサイドバー上抜け"] = _b((h > ph) & (l < pl) & (c > ph))
        ev["アウトサイドバー下抜け"] = _b((h > ph) & (l < pl) & (c < pl))
        # ラウンドナンバー(終値が刻みを跨いだ)
        step = ROUND_STEP[symbol]
        f_now = np.floor(c / step)
        f_prev = prev(f_now)
        ev["ラウンド上抜け"] = _b(f_now > f_prev)
        ev["ラウンド下抜け"] = _b(f_now < f_prev)
        # ギャップ(休場明けの始値が前の終値から乖離)
        dts = np.empty(len(ts), dtype=float)
        dts[0] = 0
        dts[1:] = np.diff(ts)
        closed = dts >= max(GAP_MIN_SECONDS, 1.5 * tf_seconds)
        gap = (o - pc) / pc
        ev["ギャップアップ"] = _b(closed & (gap >= GAP_THRESHOLD))
        ev["ギャップダウン"] = _b(closed & (gap <= -GAP_THRESHOLD))
    return ev
