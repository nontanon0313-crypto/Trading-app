"""環境認識(トレンド判定)。波動の定義(ジグザグ38.2%)に基づく。未来の情報は使わない。

トレンド状態: +1=上昇(高値・安値がともに切り上がり) / -1=下降(ともに切り下がり) / 0=レンジまたは判定不能
"""
import numpy as np

RATIO = 0.382


def zigzag_trend(h, l, ratio=RATIO):
    """各足の確定時点で分かる、直近の確定した節目だけからトレンド状態を返す。

    現在のレッグの値幅に対して ratio を超えて逆行した時点で、そのレッグの極値を節目として確定する。
    同じ足で更新と逆行が両方起きた場合は、更新が先に起きたものとして扱う。
    """
    n = len(h)
    state = np.zeros(n, dtype=np.int8)
    if n == 0:
        return state
    d = 1
    start = l[0]
    ext = h[0]
    highs, lows = [], []
    cur = 0
    for i in range(1, n):
        if d == 1:
            if h[i] > ext:
                ext = h[i]
            if l[i] <= ext - ratio * (ext - start):
                highs.append(ext)
                d = -1
                start = ext
                ext = l[i]
        else:
            if l[i] < ext:
                ext = l[i]
            if h[i] >= ext + ratio * (start - ext):
                lows.append(ext)
                d = 1
                start = ext
                ext = h[i]
        if len(highs) >= 2 and len(lows) >= 2:
            if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                cur = 1
            elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                cur = -1
            else:
                cur = 0
        state[i] = cur
    return state


def map_to_lower(sig_ts, sig_sec, htf_ts, htf_sec, htf_state):
    """上位足の状態を、下位足の各足に対応づける。
    下位足の確定時刻までに確定している上位足(確定時刻が下位足の確定時刻以前)の状態を使う。"""
    sig_end = sig_ts + sig_sec
    htf_end = htf_ts + htf_sec
    j = np.searchsorted(htf_end, sig_end, side="right") - 1
    out = np.zeros(len(sig_ts), dtype=np.int8)
    ok = j >= 0
    out[ok] = htf_state[j[ok]]
    return out


# ---------- ファンダメンタルズの環境認識 ----------
import datetime as _dt


def _nth_sunday(year, month, n):
    d = _dt.date(year, month, 1)
    first = d + _dt.timedelta(days=(6 - d.weekday()) % 7)
    return first + _dt.timedelta(weeks=n - 1)


def us_is_dst(d):
    """米国の夏時間(3月第2日曜〜11月第1日曜)かどうか"""
    return _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1)


def et_to_utc_ts(d, hh, mm):
    """米国東部時間の日付・時刻をUTCのエポック秒に変換する"""
    off = 4 if us_is_dst(d) else 5
    base = int(_dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=_dt.timezone.utc).timestamp())
    return base + off * 3600


def real_rate_state(values, lookback=20):
    """米実質金利: 20営業日前より上昇=+1 / 低下=-1 / 同じ・判定不能=0"""
    v = np.asarray(values, dtype=float)
    out = np.zeros(len(v), dtype=np.int8)
    if len(v) > lookback:
        d = v[lookback:] - v[:-lookback]
        out[lookback:] = np.where(d > 0, 1, np.where(d < 0, -1, 0))
    return out


def vix_state(values, threshold=20.0):
    """VIX: しきい値以上=+1(高い) / 未満=-1(低い)"""
    v = np.asarray(values, dtype=float)
    return np.where(v >= threshold, 1, -1).astype(np.int8)


def map_daily_to_bars(bar_ts, bar_sec, obs_days, obs_state, stale_days=10):
    """日次データ(UTCの日付をエポック日数にしたobs_days)を足に対応づける。
    足の最後の1秒が属する日の「前日」までの観測値だけを使う(当日の値は夜に公表されるため)。"""
    ref = (bar_ts + bar_sec - 1) // 86400
    allowed = ref - 1
    j = np.searchsorted(obs_days, allowed, side="right") - 1
    out = np.zeros(len(bar_ts), dtype=np.int8)
    ok = j >= 0
    fresh = ok.copy()
    fresh[ok] = (allowed[ok] - obs_days[j[ok]]) <= stale_days
    out[fresh] = obs_state[j[fresh]]
    return out


def event_state(bar_ts, bar_sec, events, window=86400):
    """重要イベント: 発表後24時間以内=2(事後) / 発表前24時間以内=1(事前) / それ以外=0(通常)。
    発表時刻は事前に公表されているため、次のイベントの時刻を使っても未来の情報にはならない。"""
    ev = np.asarray(events, dtype=np.int64)
    out = np.zeros(len(bar_ts), dtype=np.int8)
    if len(ev) == 0:
        return out
    t_end = bar_ts + bar_sec
    p = np.searchsorted(ev, t_end, side="left") - 1
    post = np.zeros(len(t_end), dtype=bool)
    hp = p >= 0
    post[hp] = (t_end[hp] - ev[p[hp]]) <= window
    nxt = p + 1
    pre = np.zeros(len(t_end), dtype=bool)
    hn = nxt < len(ev)
    pre[hn] = (ev[nxt[hn]] - t_end[hn]) <= window
    out[pre] = 1
    out[post] = 2
    return out
