# 検証ツール(research)

FXトレード検証ツール本体(`app/`など)とは別の、過去データを使った検証用のコードです。Androidのみ(Termux)で動きます。標準ライブラリとnumpyだけを使います(`pkg install python-numpy`)。

結論と経緯は `RESULTS.md` にまとめています。

## 置き場所と注意
- Termuxの `~/fx-research` で動かしています(データは `~/fx-research/data/candles.sqlite`)。このフォルダのコードは、そこへコピーして使います。
- `data/`(価格データ。約1.4GB)・`results/`・ログ・`.fred_key`(FREDのAPIキー)は、gitに入れません(`.gitignore`に設定済み)。
- 2026年1月以降のデータは、最終テスト用です。検証ツール(`research.py` `breakout.py` `fakeout.py`)は、読み込めない設定にしています。

## ツール一覧
| ファイル | 役割 |
|---|---|
| `fetch_dukascopy.py` | Dukascopyの1分足(買値・売値)を取得してDBに保存。`check` / `run` / `status` |
| `fetch_hourly.py` | Dukascopyの1時間足(月ごとのファイル)を取得してDBのh1表に保存。`check` / `run`。1時間足・4時間足・日足の検証には、1分足(1銘柄約9〜13時間)の代わりに、これで足りる(1銘柄数分〜数十分の見込み) |
| `fetch_macro.py` | FREDから米実質金利・VIX・雇用統計/CPI/FOMCの発表日を取得。`check` / `run` |
| `rules.py` `env.py` | シグナルの定義(グループ1)と、環境認識(トレンド判定・ファンダメンタルズ) |
| `research.py` | シグナルの検証(探索期間 `explore`、確認期間 `confirm`)。多重検定の補正つき |
| `breakout.py` | ブレイクで入り、逆ブレイクで決済する売買の検証(`explore` / `detail`) |
| `multi.py` | 全銘柄をまとめた、ブレイク売買の検証(1時間足・4時間足・日足)。1時間足のデータを使う。`explore` |
| `fakeout.py` | ダマシの測定。`compare` `fractal` `sequence` `volatility` `levels` `strong` `strongbreak` |
| `papertrade.py` | 仮想売買(口座なしの前向き検証)。`selftest` `init` `update` |

## 主なコマンド
```
python fetch_dukascopy.py run --symbols XAGUSD --workers 5
python fetch_hourly.py check
python fetch_hourly.py run
python breakout.py explore --symbol USDJPY --base h1
python fetch_macro.py run
python breakout.py explore
python fakeout.py compare
python papertrade.py init
python papertrade.py update
```

## 約束事
- 数値や定義を仮置きしない。1項目ずつ確認して検証する。
- 結果は、ランダムな動きの比較用データ(順序ランダム・符号ランダム)と並べて読む。
- 新しい検証は、仕込みデータで検出できることを確認してから実データで測る。
