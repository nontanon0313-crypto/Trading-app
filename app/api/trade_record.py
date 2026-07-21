"""
トレード記録API(GMOクリック証券の約定履歴を保存・参照する)
手動入力に加え、約定履歴画像をアップロードしてAIに自動読み取りさせる機能も提供する。
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Trade
from app.services.image_processor import validate_and_read_image
from app.services import claude_client
from app.services.trade_extractor import pair_trade_rows, _parse_dt

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


@router.post("/from-image")
async def create_trades_from_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """GMOクリック証券などの約定履歴スクリーンショットを読み取り、トレード記録として一括登録する"""
    image_bytes, media_type = await validate_and_read_image(file)

    try:
        rows = claude_client.extract_trade_rows(image_bytes, media_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"画像読み取りでエラーが発生しました: {e}")

    if not rows:
        raise HTTPException(status_code=422, detail="取引データを読み取れませんでした。画像がはっきり写っているか確認してください。")

    paired = pair_trade_rows(rows)

    created = []
    skipped = 0
    for t in paired:
        if t.get("entry_price") is None:
            skipped += 1
            continue
        trade = Trade(
            currency_pair=t.get("currency_pair"),
            entry_price=t.get("entry_price"),
            exit_price=t.get("exit_price"),
            profit_loss=t.get("profit_loss"),
            lot_size=t.get("lot_size"),
            entry_datetime=_parse_dt(t.get("entry_datetime")),
            exit_datetime=_parse_dt(t.get("exit_datetime")),
        )
        db.add(trade)
        created.append(trade)

    db.commit()
    for t in created:
        db.refresh(t)

    return {"created_count": len(created), "skipped_count": skipped, "trades": created}


@router.get("/{trade_id}")
def get_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")
    return trade


@router.get("/")
def list_trades(db: Session = Depends(get_db), limit: int = 100):
    return db.query(Trade).order_by(Trade.created_at.desc()).limit(limit).all()
