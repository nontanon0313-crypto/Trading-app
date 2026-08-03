"""
1日単位の振り返りAPI
1日分のチャート画像から、見送った(気づかなかった)機会や、無駄なホールドを
後付けで確認するための機能。統計・期待値計算には一切使わない参考情報。
"""
import json as _json
from datetime import datetime, timedelta
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import DailyReflection, Trade, RuleTag
from app.services.image_processor import validate_and_read_image
from app.services import claude_client
from app.services.stats_calculator import _trading_day

router = APIRouter(prefix="/api/reflection", tags=["reflection"])


def _trades_for_reflection_date(db: Session, reflection_date: str) -> list:
    """指定した集計日(7:15〜翌7:14)に該当する実トレードの一覧を返す"""
    trades = db.query(Trade).filter(Trade.profit_loss.isnot(None)).all()
    matched = []
    for t in trades:
        d = t.exit_datetime or t.entry_datetime or t.created_at
        if not d:
            continue
        if _trading_day(d) == reflection_date:
            matched.append(t)
    return matched


@router.post("/")
async def create_reflection(
    file: UploadFile = File(...),
    reflection_date: str = Form(...),
    db: Session = Depends(get_db),
):
    """1日分のチャート画像を送り、その日の振り返り分析を行う・保存する"""
    image_bytes, media_type = await validate_and_read_image(file)

    trades = _trades_for_reflection_date(db, reflection_date)
    trades_summary = []
    for t in trades:
        try:
            tags = _json.loads(t.journal_rule_tags) if t.journal_rule_tags else []
        except _json.JSONDecodeError:
            tags = []
        trades_summary.append({
            "currency_pair": t.currency_pair,
            "side": t.side,
            "entry_datetime": t.entry_datetime,
            "exit_datetime": t.exit_datetime,
            "profit_loss": t.profit_loss,
            "rule_tags": tags,
        })

    entry_tag_names = [t.name for t in db.query(RuleTag).filter(RuleTag.purpose == "entry").all()]

    try:
        result = claude_client.analyze_daily_reflection(image_bytes, media_type, trades_summary, entry_tag_names)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI分析でエラーが発生しました: {e}")

    reflection = DailyReflection(
        reflection_date=reflection_date,
        missed_opportunities=_json.dumps(result.get("missed_opportunities", []), ensure_ascii=False),
        holding_review=_json.dumps(result.get("holding_review", []), ensure_ascii=False),
        raw_ai_response=result.get("_raw_response"),
    )
    db.add(reflection)
    db.commit()
    db.refresh(reflection)

    return {
        "id": reflection.id,
        "reflection_date": reflection.reflection_date,
        "missed_opportunities": result.get("missed_opportunities", []),
        "holding_review": result.get("holding_review", []),
    }


@router.get("/")
def list_reflections(db: Session = Depends(get_db)):
    """登録済みの振り返り一覧を新しい順で返す"""
    reflections = db.query(DailyReflection).order_by(DailyReflection.reflection_date.desc()).all()
    result = []
    for r in reflections:
        try:
            missed = _json.loads(r.missed_opportunities) if r.missed_opportunities else []
        except _json.JSONDecodeError:
            missed = []
        try:
            holding = _json.loads(r.holding_review) if r.holding_review else []
        except _json.JSONDecodeError:
            holding = []
        result.append({
            "id": r.id,
            "reflection_date": r.reflection_date,
            "missed_opportunities": missed,
            "holding_review": holding,
            "created_at": r.created_at,
        })
    return result


@router.delete("/{reflection_id}")
def delete_reflection(reflection_id: int, db: Session = Depends(get_db)):
    r = db.query(DailyReflection).filter(DailyReflection.id == reflection_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="振り返りが見つかりません")
    db.delete(r)
    db.commit()
    return {"status": "deleted"}
