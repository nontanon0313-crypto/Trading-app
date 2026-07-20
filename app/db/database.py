"""
SQLite DB接続設定
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# SQLiteファイルは backend 直下の data/ フォルダに作成される
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPIの依存性注入で使うDBセッション取得関数"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """テーブルを作成する(初回起動時に実行)"""
    from app.db import models  # noqa: F401  (モデルを読み込ませるためにimport)
    Base.metadata.create_all(bind=engine)
