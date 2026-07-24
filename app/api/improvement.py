"""
AI改善提案API
統計データをもとにAIが改善案を生成する。また、20/50/100件などの節目ごとに
蓄積データに基づいた統計的分析(節目分析)も提供する。
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Trade
from app.services.stats_calculator import calculate_statistics
from app.services import claude_client

router = APIRouter(prefix="/api/improvement", tags=["improvement"])

MILESTONES = [20, 50, 100, 150, 200, 300, 500]


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


@router.get("/milestone-status")
def get_milestone_status(db: Session = Depends(get_db)):
    """現在のトレード数と、直近で到達した節目件数を返す"""
    trades = db.query(Trade).filter(Trade.profit_loss.isnot(None)).all()
    count = len(trades)
    reached = [m for m in MILESTONES if count >= m]
    return {"closed_trade_count": count, "latest_milestone": reached[-1] if reached else None}


@router.get("/milestone")
async def get_milestone_analysis(db: Session = Depends(get_db)):
    """節目件数に達したトレードデータをもとに、統計的な節目分析を行う"""
    trades = db.query(Trade).filter(Trade.profit_loss.isnot(None)).all()
    stats = calculate_statistics(trades)

    if stats["total_trades"] < MILESTONES[0]:
        raise HTTPException(
            status_code=400,
            detail=f"節目分析には最低{MILESTONES[0]}件の決済済みトレードが必要です(現在{stats['total_trades']}件)",
        )

    trades_summary = [
        {
            "currency_pair": t.currency_pair,
            "side": t.side,
            "profit_loss": t.profit_loss,
            "entry_datetime": t.entry_datetime,
            "journal_entry_reason": t.journal_entry_reason,
            "journal_exit_reason": t.journal_exit_reason,
            "journal_emotion": t.journal_emotion,
            "journal_confidence": t.journal_confidence,
            "journal_followed_rule": t.journal_followed_rule,
        }
        for t in trades
    ]

    try:
        analysis = await asyncio.to_thread(claude_client.analyze_milestone, stats, trades_summary)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"節目分析でエラーが発生しました: {e}")

    return {"statistics": stats, "analysis": analysis}
