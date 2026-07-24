"""
トレード記録API(GMOクリック証券の約定履歴を保存・参照する)
現時点では画像OCRではなく、手動入力/構造化データでの登録を基本とする。
将来的に画像からの自動読み取りを追加できるよう設計している。
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Trade

router = APIRouter(prefix="/api/trades", tags=["trades"])


class TradeCreate(BaseModel):
    analysis_id: Optional[int] = None
    currency_pair: str
    entry_price: float
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    lot_size: Optional[float] = None
    holding_time_minutes: Optional[int] = None
    entry_datetime: Optional[datetime] = None
    exit_datetime: Optional[datetime] = None


@router.post("/")
def create_trade(trade_in: TradeCreate, db: Session = Depends(get_db)):
    trade = Trade(**trade_in.model_dump())
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


@router.get("/{trade_id}")
def get_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")
    return trade


@router.get("/")
def list_trades(db: Session = Depends(get_db), limit: int = 100):
    return db.query(Trade).order_by(Trade.created_at.desc()).limit(limit).all()
