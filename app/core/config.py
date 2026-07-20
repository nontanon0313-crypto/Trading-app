"""
アプリ全体の設定。環境変数から読み込む。
"""
import os


class Settings:
    APP_NAME: str = "FX Trade Verification Tool"

    # データベース(デフォルトはローカルSQLiteファイル)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./data/fx_trade.db"
    )

    # Claude APIキー(チャート分析・改善提案に使用、無料枠あり)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # CORS設定(PWAフロントエンドからのアクセスを許可するドメイン)
    ALLOWED_ORIGINS: list[str] = os.getenv(
        "ALLOWED_ORIGINS", "*"
    ).split(",")


settings = Settings()
