"""
銘柄別レバレッジ管理API
通貨ペア/銘柄ごとにレバレッジを登録し、期待値(%)の計算に反映する。
未登録の銘柄は、デフォルトレバレッジ(環境変数 LEVERAGE、既定20倍)を使う。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import InstrumentLeverage
from app.core.config import settings

router = APIRouter(prefix="/api/leverages", tags=["leverages"])


class LeverageUpsert(BaseModel):
    currency_pair: str
    leverage: float


@router.get("/")
def list_leverages(db: Session = Depends(get_db)):
    """登録済みの銘柄別レバレッジ一覧と、デフォルト値を返す"""
    rows = db.query(InstrumentLeverage).order_by(InstrumentLeverage.currency_pair).all()
    return {
        "default_leverage": settings.LEVERAGE,
        "instruments": [{"id": r.id, "currency_pair": r.currency_pair, "leverage": r.leverage} for r in rows],
    }


@router.post("/")
def upsert_leverage(body: LeverageUpsert, db: Session = Depends(get_db)):
    """銘柄のレバレッジを登録・更新する(同じ銘柄が既にあれば上書き)"""
    existing = db.query(InstrumentLeverage).filter(InstrumentLeverage.currency_pair == body.currency_pair).first()
    if existing:
        existing.leverage = body.leverage
    else:
        existing = InstrumentLeverage(currency_pair=body.currency_pair, leverage=body.leverage)
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/{leverage_id}")
def delete_leverage(leverage_id: int, db: Session = Depends(get_db)):
    row = db.query(InstrumentLeverage).filter(InstrumentLeverage.id == leverage_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="登録が見つかりません")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


def get_leverage_map(db: Session) -> dict:
    """通貨ペア→レバレッジの辞書を返す(統計計算で使う)"""
    rows = db.query(InstrumentLeverage).all()
    return {r.currency_pair: r.leverage for r in rows}
