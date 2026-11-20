#!/usr/bin/env python3
"""ファンダメンタルズ用データの取得(FRED公式API。無料のAPIキーが必要)。

準備: https://fred.stlouisfed.org/ で無料アカウントを作り、APIキーを取得して、次のコマンドで保存する。
  echo キー > ~/fx-research/.fred_key

使い方:
  python fetch_macro.py check   # 取得できるか・データの中身を確認(DBへは書き込まない)
  python fetch_macro.py run     # 米実質金利・VIX・重要イベントの日時をDBに保存
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import env

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "candles.sqlite")
KEY_PATH = os.path.join(HERE, ".fred_key")
API = "https://api.stlouisfed.org/fred"

SERIES = {"DFII10": "米実質金利(10年物)", "VIXCLS": "VIX"}
# 雇用統計・CPIの発表日: 各月の値が「最初に公表された日」(FREDの初回リリース日)を使う。
# 値の改定日などが混ざらないよう、リリース日の一覧ではなく初回公表日で取得する。
#   種類: (FREDの系列ID, 米国東部時間の発表時刻)
INITIAL_RELEASE = {"雇用統計": ("PAYEMS", 8, 30), "CPI": ("CPIAUCSL", 8, 30)}
# FOMCの政策発表日(最終日)。出典: FRB公式「Meeting calendars and information」の各会合の声明の日付。
# 発表時刻は米国東部時間14:00。
FOMC_HOUR, FOMC_MIN = 14, 0
FOMC_STATEMENTS = [
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
]
START = "2020-01-01"
END = "2025-12-31"  # 2026年以降は最終テスト用のため取得しない


def get_key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if not k and os.path.exists(KEY_PATH):
        k = open(KEY_PATH, encoding="utf-8").read().strip()
    if not k:
        raise SystemExit("APIキーがありません。echo キー > ~/fx-research/.fred_key で保存してください")
    return k


def api(path, **params):
    params.update({"api_key": get_key(), "file_type": "json"})
    u = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    err = None
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}),
                                        timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")[:200]
            except Exception:  # noqa
                pass
            if e.code in (400, 401, 403):
                raise SystemExit(f"FRED APIがエラーを返しました(HTTP {e.code}): {body}")
            err = f"HTTP {e.code} {body}"
        except Exception as e:  # noqa
            err = str(e)
        time.sleep(3 * (i + 1))
    raise SystemExit(f"取得失敗 {path}: {err}")


def fetch_series(sid):
    j = api("series/observations", series_id=sid, observation_start=START, observation_end=END)
    out = []
    for o in j.get("observations", []):
        try:
            out.append((o["date"], float(o["value"])))
        except (ValueError, KeyError):
            continue  # 欠損(".")は除く
    return out


def fetch_initial_release_dates(sid):
    """各月の値が最初に公表された日(=発表日)の一覧"""
    j = api("series/observations", series_id=sid, realtime_start="2019-01-01", realtime_end=END,
            output_type=4, observation_start="2019-06-01", observation_end=END)
    return sorted({o["realtime_start"] for o in j.get("observations", [])
                   if START <= o["realtime_start"] <= END})


def per_year(dates):
    c = {}
    for d in dates:
        c[d[:4]] = c.get(d[:4], 0) + 1
    return " ".join(f"{y}:{n}" for y, n in sorted(c.items()))


def event_dates():
    """{種類: (日付のリスト, 時, 分)}"""
    out = {}
    for kind, (sid, hh, mm) in INITIAL_RELEASE.items():
        out[kind] = (fetch_initial_release_dates(sid), hh, mm)
    out["FOMC"] = (list(FOMC_STATEMENTS), FOMC_HOUR, FOMC_MIN)
    return out


def cmd_check(_a):
    ok = True
    for sid, label in SERIES.items():
        obs = fetch_series(sid)
        if not obs:
            print(f"NG {sid}({label}): データなし")
            ok = False
            continue
        print(f"OK {sid}({label}): {len(obs)}件 {obs[0][0]}〜{obs[-1][0]} 最後の値={obs[-1][1]}")
    for kind, (dates, hh, mm) in event_dates().items():
        print(f"{'OK' if dates else 'NG'} {kind}: {len(dates)}件 年別: {per_year(dates)}")
        print(f"   2024年: {[d for d in dates if d.startswith('2024')]}")
        ok = ok and bool(dates)
    print("\n確認ポイント: 雇用統計・CPIは年12前後であること(2025年は政府機関の閉鎖の影響で少ない可能性あり)。"
          "FOMCは年8であること。2024年の日付が公式の発表日と合っていること。")
    return 0 if ok else 1


def cmd_run(_a):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS macro(series TEXT, date TEXT, value REAL, PRIMARY KEY(series, date));
    CREATE TABLE IF NOT EXISTS events(kind TEXT, ts INTEGER, PRIMARY KEY(kind, ts));
    """)
    for sid, label in SERIES.items():
        obs = fetch_series(sid)
        con.executemany("INSERT OR REPLACE INTO macro VALUES(?,?,?)", [(sid, d, v) for d, v in obs])
        print(f"{sid}({label}): {len(obs)}件を保存")
    con.execute("DELETE FROM events")
    for kind, (dates, hh, mm) in event_dates().items():
        rows = [(kind, env.et_to_utc_ts(dt.date.fromisoformat(d), hh, mm)) for d in dates]
        con.executemany("INSERT OR REPLACE INTO events VALUES(?,?)", rows)
        print(f"{kind}: {len(rows)}件を保存")
    con.commit()
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["check", "run"])
    a = p.parse_args()
    sys.exit({"check": cmd_check, "run": cmd_run}[a.cmd](a))


if __name__ == "__main__":
    main()
