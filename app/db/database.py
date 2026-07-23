"""
DB接続設定(SQLiteまたはPostgreSQLに対応)
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """テーブルを作成する(初回起動時に実行)。既存テーブルには不足カラムを追加する"""
    from app.db import models  # noqa: F401  (モデルを読み込ませるためにimport)
    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()


def _migrate_add_missing_columns():
    """既存のtradesテーブルに、新しく追加したカラムが無ければ追加する(Postgres/SQLite両対応)"""
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    if "trades" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("trades")}

    new_columns = {
        "side": "VARCHAR",
        "journal_entry_reason": "TEXT",
        "journal_scenario": "TEXT",
        "journal_planned_take_profit": "FLOAT",
        "journal_stop_loss_basis": "TEXT",
        "journal_confidence": "INTEGER",
        "journal_anxiety": "TEXT",
        "journal_skip_consideration": "TEXT",
        "journal_followed_rule": "VARCHAR",
        "journal_emotion": "VARCHAR",
        "journal_pre_notes": "TEXT",
        "journal_exit_reason": "TEXT",
        "journal_as_expected": "VARCHAR",
        "journal_improvement": "TEXT",
        "journal_post_notes": "TEXT",
    }

    with engine.connect() as conn:
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                try:
                    conn.execute(text(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    conn.rollback()

