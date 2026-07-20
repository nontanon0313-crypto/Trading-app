# FXトレード検証ツール - バックエンド

TradingViewのチャート画像とGMOクリック証券のトレード結果を使い、
FXトレードの検証・統計・改善提案を行うツールのバックエンド(API)です。

## 機能

- `POST /api/chart-analysis/` チャート画像をアップロードしてAI分析(エントリー/損切り/利確など)
- `POST /api/trades/` トレード記録の登録
- `POST /api/verifications/` 分析結果と実トレードの検証記録
- `GET /api/statistics/` 勝率・PF・最大DDなどの統計
- `GET /api/improvement/` AIによる改善提案

## ローカルでの起動(参考)

```bash
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEYを設定する
uvicorn app.main:app --reload
```

起動後、`http://localhost:8000/docs` でAPIの動作確認ができます。

## 無料クラウドへのデプロイ(Render想定・Android端末のみでもOK)

1. このリポジトリをGitHubにpushする(GitHub Webエディタでも可)
2. [render.com](https://render.com) にアクセスし、GitHubアカウントでログイン
3. 「New +」→「Web Service」を選択し、このリポジトリを接続
4. 設定項目
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Environment Variables に `ANTHROPIC_API_KEY` を追加
6. Deployを実行 → 発行されたURL(例: `https://xxxx.onrender.com`)がAPIのアドレスになる

これで、スマホのブラウザ(PWAフロントエンド)からこのURLにアクセスして利用できます。

※Renderの無料プランはしばらく使わないとスリープするため、初回アクセス時に起動待ちが発生することがあります。

## ディレクトリ構成

```
fx_trade_backend/
├── app/
│   ├── main.py              # エントリーポイント
│   ├── api/                 # 各機能のAPIエンドポイント
│   ├── services/            # AI連携・統計計算などのロジック
│   ├── db/                  # DBモデル・接続設定
│   └── core/                # 設定(環境変数)
├── tests/
├── requirements.txt
└── .env.example
```

## 次のステップ

- PWAフロントエンド(HTML/JS)の作成
- チャート/トレード履歴画像アップロード画面
- 統計・改善提案の表示画面
