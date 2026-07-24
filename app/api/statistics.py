"""
統計分析API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Trade
from app.services.stats_calculator import calculate_statistics, calculate_daily_calendar

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


@router.get("/")
def get_statistics(db: Session = Depends(get_db)):
    """蓄積された全トレードから統計指標を計算して返す"""
    trades = db.query(Trade).all()
    return calculate_statistics(trades)


@router.get("/calendar")
def get_calendar(db: Session = Depends(get_db)):
    """日別の損益・トレード数・感情をカレンダーヒートマップ用に返す"""
    trades = db.query(Trade).all()
    return calculate_daily_calendar(trades)
