"""
DB接続設定(SQLiteまたはPostgreSQLに対応)
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
# NeonなどのPostgresは "postgres://" 形式で発行されることがあるが、
# SQLAlchemyは "postgresql://" を要求するため変換する
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

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
    """テーブルを作成する(初回起動時に実行)。既存テーブルには不足カラムを追加する"""
    from app.db import models  # noqa: F401  (モデルを読み込ませるためにimport)
    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()
    _seed_default_rule_tags()


def _seed_default_rule_tags():
    """デフォルトのルールタグのうち、まだ登録されていないものだけを追加する(タグ単位で冪等)"""
    from app.db.models import RuleTag
    from app.core.default_rule_tags import DEFAULT_RULE_TAGS, DEFAULT_EXIT_REASON_TAGS

    db = SessionLocal()
    try:
        # 既存タグでpurposeが未設定(NULL)のものは、entry(エントリー用)として扱う
        db.query(RuleTag).filter(RuleTag.purpose.is_(None)).update({RuleTag.purpose: "entry"})
        db.commit()

        existing = {(t.category, t.name, t.purpose) for t in db.query(RuleTag).all()}

        for category, names in DEFAULT_RULE_TAGS.items():
            for name in names:
                if (category, name, "entry") not in existing:
                    db.add(RuleTag(category=category, name=name, purpose="entry"))

        for category, names in DEFAULT_EXIT_REASON_TAGS.items():
            for name in names:
                if (category, name, "exit") not in existing:
                    db.add(RuleTag(category=category, name=name, purpose="exit"))

        db.commit()
    finally:
        db.close()


def _migrate_add_missing_columns():
    """既存テーブルに、新しく追加したカラムが無ければ追加する(Postgres/SQLite両対応)"""
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    tables_to_migrate = {
        "trades": {
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
            "ai_review": "TEXT",
            "ai_review_created_at": "TIMESTAMP",
            "journal_pre_committed_at": "TIMESTAMP",
            "journal_rule_tags": "TEXT",
            "journal_exit_reason_tags": "TEXT",
        },
        "chart_analyses": {
            "tag_evaluations": "TEXT",
            "tag_agreements": "TEXT",
            "tag_conflicts": "TEXT",
            "scenario_forecast": "TEXT",
            "timeframes_used": "TEXT",
        },
        "rule_tags": {
            "purpose": "VARCHAR",
        },
    }

    with engine.connect() as conn:
        for table_name, new_columns in tables_to_migrate.items():
            if table_name not in table_names:
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            for col_name, col_type in new_columns.items():
                if col_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                    except Exception:
                        conn.rollback()
