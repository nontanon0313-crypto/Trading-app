"""
仮説検証API
「この条件の組み合わせは期待値が高そうだ」という仮説を登録し、
登録日以降に発生したトレードだけを使って再現性を検証する(後出しの検証を防ぐため)。
"""
import json as _json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Hypothesis, Trade
from app.services.stats_calculator import _return_pct

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])


class HypothesisCreate(BaseModel):
    name: str
    tags: List[str]
    notes: Optional[str] = None


def _trade_tags(trade: Trade) -> list:
    if not trade.journal_rule_tags:
        return []
    try:
        return _json.loads(trade.journal_rule_tags)
    except (ValueError, TypeError):
        return []


def _verify(db: Session, hypothesis: Hypothesis) -> dict:
    """この仮説の条件(タグの完全一致=AND)に該当するトレードの成績を、
    登録日以降(検証用)と全期間(参考)の両方で計算する"""
    try:
        target_tags = set(_json.loads(hypothesis.tags))
    except (ValueError, TypeError):
        target_tags = set()

    all_matching = [
        t for t in db.query(Trade).filter(Trade.profit_loss.isnot(None)).all()
        if target_tags.issubset(set(_trade_tags(t)))
    ]

    post_registration = [
        t for t in all_matching
        if t.entry_datetime and t.entry_datetime > hypothesis.created_at
    ]

    def _summarize(trades):
        if not trades:
            return {"trade_count": 0, "win_rate": None, "expectancy_pct": None, "expectancy": None, "total_profit_loss": None}
        wins = [t for t in trades if t.profit_loss > 0]
        total = sum(t.profit_loss for t in trades)
        pct_values = [v for v in (_return_pct(t) for t in trades) if v is not None]
        return {
            "trade_count": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 2),
            "expectancy_pct": round(sum(pct_values) / len(pct_values), 3) if pct_values else None,
            "expectancy": round(total / len(trades), 2),
            "total_profit_loss": round(total, 2),
        }

    return {
        "since_registration": _summarize(post_registration),
        "all_time_reference": _summarize(all_matching),
    }


@router.get("/")
def list_hypotheses(db: Session = Depends(get_db)):
    """登録済みの仮説と、それぞれの検証結果を返す"""
    hypotheses = db.query(Hypothesis).order_by(Hypothesis.created_at.desc()).all()
    result = []
    for h in hypotheses:
        try:
            tags = _json.loads(h.tags)
        except (ValueError, TypeError):
            tags = []
        result.append({
            "id": h.id,
            "name": h.name,
            "tags": tags,
            "notes": h.notes,
            "created_at": h.created_at,
            "verification": _verify(db, h),
        })
    return result


@router.post("/")
def create_hypothesis(h_in: HypothesisCreate, db: Session = Depends(get_db)):
    """新しい仮説を登録する(この時点をもって「登録後データ」の起点とする)"""
    if not h_in.tags:
        raise HTTPException(status_code=400, detail="タグを最低1つ選んでください")

    hypothesis = Hypothesis(
        name=h_in.name,
        tags=_json.dumps(h_in.tags, ensure_ascii=False),
        notes=h_in.notes,
    )
    db.add(hypothesis)
    db.commit()
    db.refresh(hypothesis)
    return hypothesis


@router.delete("/{hypothesis_id}")
def delete_hypothesis(hypothesis_id: int, db: Session = Depends(get_db)):
    h = db.query(Hypothesis).filter(Hypothesis.id == hypothesis_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="仮説が見つかりません")
    db.delete(h)
    db.commit()
    return {"status": "deleted"}
