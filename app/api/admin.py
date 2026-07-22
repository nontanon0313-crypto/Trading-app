"""
データ管理API(全データの手動削除)
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ChartAnalysis, Trade, Verification, ChangeLog

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.delete("/clear-data")
def clear_all_data(db: Session = Depends(get_db)):
    """チャート分析・トレード記録・検証結果・変更履歴をすべて削除する"""
    db.query(Verification).delete()
    db.query(Trade).delete()
    db.query(ChartAnalysis).delete()
    db.query(ChangeLog).delete()
    db.commit()
    return {"status": "cleared"}
