"""
AI改善提案API
統計データをもとにClaudeが改善案を生成する
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Trade
from app.services.stats_calculator import calculate_statistics
from app.services import claude_client

router = APIRouter(prefix="/api/improvement", tags=["improvement"])


@router.get("/")
def get_improvement_suggestions(db: Session = Depends(get_db)):
    """統計データをもとにAIによる改善提案を生成する"""
    trades = db.query(Trade).all()
    stats = calculate_statistics(trades)

    if stats["total_trades"] == 0:
        raise HTTPException(
            status_code=400,
            detail="改善提案を生成するにはトレード記録が必要です",
        )

    try:
        suggestions = claude_client.generate_improvement_suggestions(stats)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI改善提案でエラーが発生しました: {e}")

    return {"statistics": stats, "suggestions": suggestions}
