"""
チャート分析結果と実トレード結果の検証API
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Verification, Trade

router = APIRouter(prefix="/api/verifications", tags=["verifications"])


class VerificationCreate(BaseModel):
    trade_id: int
    entry_was_appropriate: Optional[str] = None
    stop_loss_was_appropriate: Optional[str] = None
    take_profit_was_appropriate: Optional[str] = None
    skip_was_correct: Optional[str] = None
    working_reasons: Optional[str] = None
    failing_reasons: Optional[str] = None
    notes: Optional[str] = None


@router.post("/")
def create_verification(v_in: VerificationCreate, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == v_in.trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="対象のトレード記録が見つかりません")

    verification = Verification(**v_in.model_dump())
    db.add(verification)
    db.commit()
    db.refresh(verification)
    return verification


@router.get("/{verification_id}")
def get_verification(verification_id: int, db: Session = Depends(get_db)):
    v = db.query(Verification).filter(Verification.id == verification_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="検証結果が見つかりません")
    return v


@router.get("/")
def list_verifications(db: Session = Depends(get_db), limit: int = 100):
    return db.query(Verification).order_by(Verification.created_at.desc()).limit(limit).all()
