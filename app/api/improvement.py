"""
AI改善提案API
統計データをもとにAIが改善案を生成する。また、20/50/100件などの節目ごとに
蓄積データに基づいた統計的分析(節目分析)も提供する。
"""
import asyncio
import json as _json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Trade
from app.services.stats_calculator import calculate_statistics
from app.api.leverages import get_leverage_map
from app.services import claude_client

router = APIRouter(prefix="/api/improvement", tags=["improvement"])

def _strip_unfilled(stats: dict) -> dict:
    """「未入力」グループを内訳から除外してから返す(AIが未入力を根拠に分析しないように)"""
    stats = dict(stats)
    for key in ("by_entry_reason", "by_exit_reason", "by_emotion", "by_confidence", "by_reversal_sign"):
        if key in stats and isinstance(stats[key], dict):
            stats[key] = {k: v for k, v in stats[key].items() if k != "未入力"}
    return stats


MILESTONES = [20, 50, 100, 150, 200, 300, 500]


@router.get("/")
def get_improvement_suggestions(db: Session = Depends(get_db)):
    """統計データをもとにAIによる改善提案を生成する"""
    trades = db.query(Trade).all()
    stats = calculate_statistics(trades, leverage_map=get_leverage_map(db))

    if stats["total_trades"] == 0:
        raise HTTPException(
            status_code=400,
            detail="改善提案を生成するにはトレード記録が必要です",
        )

    try:
        # ポジション方向・時間帯・曜日は分析対象外のため、AIに渡す前に除外する
        # (時間帯・曜日はエントリーカテゴリに属さず、トレードは毎日行うため回避提案の根拠にしない)
        EXCLUDE_KEYS = {"by_side", "average_win", "average_loss", "average_risk_reward", "by_hour", "by_weekday"}
        stats_for_ai = _strip_unfilled({k: v for k, v in stats.items() if k not in EXCLUDE_KEYS})
        suggestions = claude_client.generate_improvement_suggestions(stats_for_ai)
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
    stats = calculate_statistics(trades, leverage_map=get_leverage_map(db))

    if stats["total_trades"] < MILESTONES[0]:
        raise HTTPException(
            status_code=400,
            detail=f"節目分析には最低{MILESTONES[0]}件の決済済みトレードが必要です(現在{stats['total_trades']}件)",
        )

    trades_summary = []
    for t in trades:
        try:
            tags = _json.loads(t.journal_rule_tags) if t.journal_rule_tags else []
        except (ValueError, TypeError):
            tags = []
        try:
            exit_tags = _json.loads(t.journal_exit_reason_tags) if t.journal_exit_reason_tags else []
        except (ValueError, TypeError):
            exit_tags = []
        is_precommitted = bool(
            t.journal_pre_committed_at and t.exit_datetime
            and t.journal_pre_committed_at < t.exit_datetime
        )
        trades_summary.append({
            "currency_pair": t.currency_pair,
            "profit_loss": t.profit_loss,
            # entry_datetimeは意図的に含めない(時間帯・曜日はエントリーカテゴリに属さないため分析対象外)
            "rule_tags": tags,
            "exit_reason_tags": exit_tags,
            "is_precommitted": is_precommitted,
            "journal_entry_reason": t.journal_entry_reason,
            "journal_exit_reason": t.journal_exit_reason,
            "journal_emotion": t.journal_emotion,
            "journal_confidence": t.journal_confidence,
            "journal_followed_rule": t.journal_followed_rule,
        })

    try:
        # ポジション方向・時間帯・曜日は分析対象外のため、統計データからも除外してAIに渡す
        # (時間帯・曜日はエントリーカテゴリに属さず、トレードは毎日行うため回避提案の根拠にしない)
        EXCLUDE_KEYS = {"by_side", "average_win", "average_loss", "average_risk_reward", "by_hour", "by_weekday"}
        stats_for_ai = _strip_unfilled({k: v for k, v in stats.items() if k not in EXCLUDE_KEYS})
        analysis = await asyncio.to_thread(claude_client.analyze_milestone, stats_for_ai, trades_summary)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"節目分析でエラーが発生しました: {e}")

    return {"statistics": stats, "analysis": analysis}
