"""
チャート画像分析API
"""
import asyncio
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ChartAnalysis
from app.services.image_processor import validate_and_read_image
from app.services import claude_client

router = APIRouter(prefix="/api/chart-analysis", tags=["chart-analysis"])


@router.post("/")
async def analyze_chart(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """TradingViewのチャート画像をアップロードし、AI分析結果を返す・保存する"""
    image_bytes, media_type = await validate_and_read_image(file)

    try:
        result = await asyncio.to_thread(claude_client.analyze_chart_image, image_bytes, media_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI分析でエラーが発生しました: {e}")

    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    analysis = ChartAnalysis(
        currency_pair=result.get("currency_pair"),
        direction=result.get("direction"),
        entry_price=result.get("entry_price"),
        stop_loss=result.get("stop_loss"),
        take_profit=result.get("take_profit"),
        risk_reward=result.get("risk_reward"),
        trend=result.get("trend"),
        support_resistance=result.get("support_resistance"),
        dow_theory=result.get("dow_theory"),
        candle_pattern=result.get("candle_pattern"),
        moving_average=result.get("moving_average"),
        rsi_macd=result.get("rsi_macd"),
        volatility=result.get("volatility"),
        entry_reason=result.get("entry_reason"),
        skip_reason=result.get("skip_reason"),
        raw_ai_response=result.get("_raw_response"),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return {"id": analysis.id, **result}


@router.get("/{analysis_id}")
def get_analysis(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.query(ChartAnalysis).filter(ChartAnalysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="分析結果が見つかりません")
    return analysis


@router.get("/")
def list_analyses(db: Session = Depends(get_db), limit: int = 50):
    return db.query(ChartAnalysis).order_by(ChartAnalysis.created_at.desc()).limit(limit).all()
