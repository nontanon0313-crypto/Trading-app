"""
仮説検証API
「10時からずっと上がる」「ロングとショートで動きが違う」のような、時間帯・方向についての
仮説を登録し、登録日以降に発生したトレードだけを使って再現性を検証する(後出しの検証を防ぐため)。

タグの組み合わせに基づく仮説(例:トレンドライン+高値ブレイク)は、エントリー時に既にタグを
選択済みでデータが十分取れているため、この機能では扱わない。「内訳」画面(エントリールール
タグ別)でいつでも期待値を確認できる。
"""
import json as _json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Hypothesis, Trade
from app.services.stats_calculator import _return_pct
from app.api.leverages import get_leverage_map

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])


class HypothesisCreate(BaseModel):
    name: str
    notes: Optional[str] = None
    entry_hour_start: Optional[int] = None  # 0-23
    entry_hour_end: Optional[int] = None    # 0-23
    direction: Optional[str] = None         # "buy" | "sell" | None


def _matches_hypothesis(trade: Trade, hypothesis: Hypothesis) -> bool:
    """トレードがこの仮説の条件(時間帯・方向)に合致するか判定する"""
    if hypothesis.direction and trade.side != hypothesis.direction:
        return False

    if hypothesis.entry_hour_start is not None or hypothesis.entry_hour_end is not None:
        if not trade.entry_datetime:
            return False
        hour = trade.entry_datetime.hour
        start = hypothesis.entry_hour_start if hypothesis.entry_hour_start is not None else 0
        end = hypothesis.entry_hour_end if hypothesis.entry_hour_end is not None else 23
        if start <= end:
            if not (start <= hour <= end):
                return False
        else:
            # 例: 22時〜翌3時のような日をまたぐ範囲指定
            if not (hour >= start or hour <= end):
                return False

    return True


def _verify(db: Session, hypothesis: Hypothesis) -> dict:
    """この仮説の条件(時間帯・方向)に該当するトレードの成績を、
    登録日以降(検証用)と全期間(参考)の両方で計算する"""
    all_matching = [
        t for t in db.query(Trade).filter(Trade.profit_loss.isnot(None)).all()
        if _matches_hypothesis(t, hypothesis)
    ]

    post_registration = [
        t for t in all_matching
        if t.entry_datetime and t.entry_datetime > hypothesis.created_at
    ]

    leverage_map = get_leverage_map(db)

    def _summarize(trades):
        if not trades:
            return {"trade_count": 0, "win_rate": None, "expectancy_pct": None, "expectancy": None, "total_profit_loss": None}
        wins = [t for t in trades if t.profit_loss > 0]
        total = sum(t.profit_loss for t in trades)
        pct_values = [v for v in (_return_pct(t, leverage_map) for t in trades) if v is not None]
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
        result.append({
            "id": h.id,
            "name": h.name,
            "notes": h.notes,
            "entry_hour_start": h.entry_hour_start,
            "entry_hour_end": h.entry_hour_end,
            "direction": h.direction,
            "created_at": h.created_at,
            "verification": _verify(db, h),
        })
    return result


@router.post("/")
def create_hypothesis(h_in: HypothesisCreate, db: Session = Depends(get_db)):
    """新しい仮説を登録する(この時点をもって「登録後データ」の起点とする)"""
    if h_in.entry_hour_start is None and h_in.entry_hour_end is None and not h_in.direction:
        raise HTTPException(status_code=400, detail="時間帯か方向のどちらか一方は指定してください")

    for hour in (h_in.entry_hour_start, h_in.entry_hour_end):
        if hour is not None and not (0 <= hour <= 23):
            raise HTTPException(status_code=400, detail="時刻は0〜23の範囲で指定してください")

    if h_in.direction and h_in.direction not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="方向はbuyまたはsellで指定してください")

    hypothesis = Hypothesis(
        name=h_in.name,
        tags="[]",
        notes=h_in.notes,
        entry_hour_start=h_in.entry_hour_start,
        entry_hour_end=h_in.entry_hour_end,
        direction=h_in.direction,
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
