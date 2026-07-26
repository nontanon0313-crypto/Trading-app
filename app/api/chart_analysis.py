"""
チャート画像分析API(マルチタイムフレーム対応)
"""
import asyncio
import json as _json
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ChartAnalysis, RuleTag
from app.services.image_processor import validate_and_read_image
from app.services import claude_client

router = APIRouter(prefix="/api/chart-analysis", tags=["chart-analysis"])


@router.post("/")
async def analyze_chart(
    files: List[UploadFile] = File(...),
    timeframes: List[str] = Form(...),
    db: Session = Depends(get_db),
):
    """1〜3枚のTradingViewチャート画像(時間足ラベル付き)をアップロードし、
    マルチタイムフレームのAI分析結果(ルールタグ網羅評価・シナリオ予測を含む)を返す・保存する"""
    if len(files) != len(timeframes):
        raise HTTPException(status_code=400, detail="画像の枚数と時間足の数が一致しません")
    if len(files) > 3:
        raise HTTPException(status_code=400, detail="画像は最大3枚までです")

    images = []
    for f, tf in zip(files, timeframes):
        image_bytes, media_type = await validate_and_read_image(f)
        images.append({"bytes": image_bytes, "media_type": media_type, "timeframe": tf})

    rule_tag_names = [t.name for t in db.query(RuleTag).all()]

    try:
        # 同期処理のAI呼び出しがイベントループをブロックしないよう別スレッドで実行
        result = await asyncio.to_thread(claude_client.analyze_chart_image, images, rule_tag_names)
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
        tag_evaluations=_json.dumps(result.get("tag_evaluations", []), ensure_ascii=False),
        tag_agreements=result.get("agreement_points"),
        tag_conflicts=result.get("conflict_points"),
        scenario_forecast=_json.dumps(result.get("scenario_forecast", []), ensure_ascii=False),
        timeframes_used=_json.dumps(timeframes, ensure_ascii=False),
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
    return _serialize_analysis(analysis)


@router.get("/")
def list_analyses(db: Session = Depends(get_db), limit: int = 50):
    analyses = db.query(ChartAnalysis).order_by(ChartAnalysis.created_at.desc()).limit(limit).all()
    return [_serialize_analysis(a) for a in analyses]


def _serialize_analysis(analysis: ChartAnalysis) -> dict:
    data = {c.name: getattr(analysis, c.name) for c in analysis.__table__.columns}
    for field in ("tag_evaluations", "scenario_forecast", "timeframes_used"):
        raw = getattr(analysis, field)
        try:
            data[field] = _json.loads(raw) if raw else []
        except (ValueError, TypeError):
            data[field] = []
    return data
