"""
トレード記録API(GMOクリック証券の約定履歴を保存・参照する)
約定履歴画像からの自動登録に加え、各トレードにエントリー前/決済後の
日記(ジャーナル)・事前記録タイムスタンプ・複合ルールタグを追記できるようにする。
"""
import asyncio
import json as _json
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Trade, ChartAnalysis
from app.services.image_processor import validate_and_read_image
from app.services import claude_client
from app.services.trade_extractor import pair_trade_rows, _parse_dt

router = APIRouter(prefix="/api/trades", tags=["trades"])

# エントリー前の記録とみなすフィールド(これらが初めて保存された時刻を事前記録日時とする)
PRE_TRADE_FIELDS = {
    "journal_entry_reason", "journal_scenario", "journal_planned_take_profit",
    "journal_stop_loss_basis", "journal_confidence", "journal_anxiety",
    "journal_skip_consideration", "journal_followed_rule", "journal_emotion",
    "journal_pre_notes", "journal_rule_tags",
}


class TradeCreate(BaseModel):
    analysis_id: Optional[int] = None
    currency_pair: str
    side: Optional[str] = None
    entry_price: float
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    lot_size: Optional[float] = None
    holding_time_minutes: Optional[int] = None
    entry_datetime: Optional[datetime] = None
    exit_datetime: Optional[datetime] = None


class TradeJournalUpdate(BaseModel):
    """トレード日記(エントリー前・決済後)の更新用。すべて任意項目。"""
    journal_entry_reason: Optional[str] = None
    journal_scenario: Optional[str] = None
    journal_planned_take_profit: Optional[float] = None
    journal_stop_loss_basis: Optional[str] = None
    journal_confidence: Optional[int] = None
    journal_anxiety: Optional[str] = None
    journal_skip_consideration: Optional[str] = None
    journal_followed_rule: Optional[str] = None
    journal_emotion: Optional[str] = None
    journal_pre_notes: Optional[str] = None
    journal_exit_reason: Optional[str] = None
    journal_as_expected: Optional[str] = None
    journal_improvement: Optional[str] = None
    journal_post_notes: Optional[str] = None
    journal_rule_tags: Optional[List[str]] = None


@router.post("/")
def create_trade(trade_in: TradeCreate, db: Session = Depends(get_db)):
    trade = Trade(**trade_in.model_dump())
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


@router.post("/from-image/preview")
async def preview_trades_from_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """GMOクリック証券などの約定履歴スクリーンショットを読み取り、取り込み候補を提示する(まだ保存しない)"""
    image_bytes, media_type = await validate_and_read_image(file)

    try:
        rows = await asyncio.to_thread(claude_client.extract_trade_rows, image_bytes, media_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"画像読み取りでエラーが発生しました: {e}")

    if not rows:
        raise HTTPException(status_code=422, detail="取引データを読み取れませんでした。画像がはっきり写っているか確認してください。")

    paired = pair_trade_rows(rows)

    # 決済日時の古い順に並べ、バッチ内で候補が重複しないよう順番に割り当てる
    paired_with_price = [t for t in paired if t.get("entry_price") is not None]
    skipped = len(paired) - len(paired_with_price)
    paired_with_price.sort(key=lambda t: t.get("exit_datetime") or "")

    candidate_pools = {}  # (currency_pair, side) -> 候補リスト(古い順、消費される)
    items = []
    for t in paired_with_price:
        key = (t.get("currency_pair"), t.get("side"))
        if key not in candidate_pools:
            candidate_pools[key] = _find_candidate_open_trades(db, t)

        full_candidates = candidate_pools[key]
        # このバッチ内ですでに他の行に割り当て済みの候補は、提案先から除外する
        already_assigned_ids = {it["suggested_trade_id"] for it in items if it["suggested_trade_id"]}
        remaining = [c for c in full_candidates if c["id"] not in already_assigned_ids]

        items.append({
            **t,
            "suggested_trade_id": remaining[0]["id"] if remaining else None,
            "candidates": full_candidates,
        })

    return {"items": items, "skipped_count": skipped}


class ImportItem(BaseModel):
    trade_id: Optional[int] = None  # 指定があれば既存トレードを更新、無ければ新規作成
    currency_pair: str
    side: Optional[str] = None
    entry_price: float
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    lot_size: Optional[float] = None
    entry_datetime: Optional[datetime] = None
    exit_datetime: Optional[datetime] = None


class ImportConfirmRequest(BaseModel):
    items: List[ImportItem]


@router.post("/from-image/confirm")
def confirm_trades_from_image(body: ImportConfirmRequest, db: Session = Depends(get_db)):
    """プレビューをユーザーが確認・修正した内容で、実際にトレード記録へ反映する"""
    created = []
    matched = []

    for item in body.items:
        if item.trade_id:
            trade = db.query(Trade).filter(Trade.id == item.trade_id).first()
            if not trade:
                continue
            trade.exit_price = item.exit_price
            trade.profit_loss = item.profit_loss
            trade.exit_datetime = item.exit_datetime
            if not trade.lot_size and item.lot_size:
                trade.lot_size = item.lot_size
            matched.append(trade)
        else:
            trade = Trade(
                currency_pair=item.currency_pair,
                side=item.side,
                entry_price=item.entry_price,
                exit_price=item.exit_price,
                profit_loss=item.profit_loss,
                lot_size=item.lot_size,
                entry_datetime=item.entry_datetime,
                exit_datetime=item.exit_datetime,
            )
            db.add(trade)
            created.append(trade)

    db.commit()
    for t in created + matched:
        db.refresh(t)

    return {
        "created_count": len(created),
        "matched_count": len(matched),
        "trades": created + matched,
    }


def _find_candidate_open_trades(db: Session, row: dict) -> list:
    """同じ通貨ペア・方向の未決済トレードを、古い順(FIFO推奨順)で候補として返す"""
    currency_pair = row.get("currency_pair")
    side = row.get("side")
    if not currency_pair:
        return []

    candidates = db.query(Trade).filter(
        Trade.currency_pair == currency_pair,
        Trade.exit_price.is_(None),
    ).all()

    if side:
        candidates = [c for c in candidates if not c.side or c.side == side]

    candidates.sort(key=lambda c: c.entry_datetime or c.created_at)

    return [
        {
            "id": c.id,
            "entry_price": c.entry_price,
            "entry_datetime": c.entry_datetime,
            "journal_entry_reason": c.journal_entry_reason,
        }
        for c in candidates
    ]


class TradeUpdate(BaseModel):
    """トレードの基本情報(通貨ペア・方向・価格・ロット等)を後から修正するための項目。すべて任意。"""
    currency_pair: Optional[str] = None
    side: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    lot_size: Optional[float] = None
    entry_datetime: Optional[datetime] = None
    exit_datetime: Optional[datetime] = None


@router.patch("/{trade_id}")
def update_trade(trade_id: int, trade_in: TradeUpdate, db: Session = Depends(get_db)):
    """入力ミス(ロング/ショートの取り違え、価格の誤入力等)を後から修正する"""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")

    for field, value in trade_in.model_dump(exclude_unset=True).items():
        setattr(trade, field, value)

    db.commit()
    db.refresh(trade)
    return _serialize_trade(trade)


@router.patch("/{trade_id}/link-analysis")
def link_analysis(trade_id: int, body: dict, db: Session = Depends(get_db)):
    """このトレードに、既存のチャート分析結果を紐付ける"""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")

    analysis_id = body.get("analysis_id")
    analysis = db.query(ChartAnalysis).filter(ChartAnalysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="チャート分析結果が見つかりません")

    trade.analysis_id = analysis_id
    db.commit()
    db.refresh(trade)
    return trade


@router.get("/{trade_id}/linked-analysis")
def get_linked_analysis(trade_id: int, db: Session = Depends(get_db)):
    """このトレードに紐付いているチャート分析結果を返す(無ければnull)"""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")
    if not trade.analysis_id:
        return None

    return db.query(ChartAnalysis).filter(ChartAnalysis.id == trade.analysis_id).first()


@router.delete("/{trade_id}")
def delete_trade(trade_id: int, db: Session = Depends(get_db)):
    """トレード記録を1件削除する(重複統合などのため)"""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")
    db.delete(trade)
    db.commit()
    return {"status": "deleted"}


@router.get("/currency-pairs")
def list_currency_pairs(db: Session = Depends(get_db)):
    """過去に使われた通貨ペア名の一覧(表記ゆれ防止のための選択候補用)"""
    from app.db.models import ChartAnalysis

    trade_pairs = {r[0] for r in db.query(Trade.currency_pair).distinct().all() if r[0]}
    analysis_pairs = {r[0] for r in db.query(ChartAnalysis.currency_pair).distinct().all() if r[0]}
    return sorted(trade_pairs | analysis_pairs)


@router.get("/rule-tags")
def list_rule_tags(db: Session = Depends(get_db)):
    """過去に使われたルールタグの一覧(入力候補用)を返す"""
    trades = db.query(Trade).filter(Trade.journal_rule_tags.isnot(None)).all()
    tags = set()
    for t in trades:
        try:
            tags.update(_json.loads(t.journal_rule_tags))
        except (ValueError, TypeError):
            continue
    return sorted(tags)


@router.get("/{trade_id}")
def get_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")
    return _serialize_trade(trade)


@router.patch("/{trade_id}/journal")
def update_trade_journal(trade_id: int, journal_in: TradeJournalUpdate, db: Session = Depends(get_db)):
    """トレード日記(エントリー前・決済後の記録)を更新する。
    エントリー前項目が初めて保存された時、その時刻を事前記録日時として記録する(編集は自由)。
    """
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")

    updates = journal_in.model_dump(exclude_unset=True)

    if trade.journal_pre_committed_at is None and any(k in PRE_TRADE_FIELDS for k in updates):
        trade.journal_pre_committed_at = datetime.utcnow()

    for field, value in updates.items():
        if field == "journal_rule_tags":
            trade.journal_rule_tags = _json.dumps(value, ensure_ascii=False) if value else None
        else:
            setattr(trade, field, value)

    db.commit()
    db.refresh(trade)
    return _serialize_trade(trade)


@router.get("/")
def list_trades(db: Session = Depends(get_db), limit: int = 100):
    trades = db.query(Trade).order_by(Trade.created_at.desc()).limit(limit).all()
    return [_serialize_trade(t) for t in trades]


@router.post("/{trade_id}/review")
async def review_trade(trade_id: int, db: Session = Depends(get_db)):
    """このトレードについて、AIレビューを実行する(紐付いたチャート分析があれば併せて考慮する)"""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="トレード記録が見つかりません")

    is_precommitted = bool(
        trade.journal_pre_committed_at and trade.exit_datetime
        and trade.journal_pre_committed_at < trade.exit_datetime
    )

    trade_data = {
        "currency_pair": trade.currency_pair,
        "side": trade.side,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "profit_loss": trade.profit_loss,
        "lot_size": trade.lot_size,
        "holding_time_minutes": trade.holding_time_minutes,
        "journal_entry_reason": trade.journal_entry_reason,
        "journal_scenario": trade.journal_scenario,
        "journal_planned_take_profit": trade.journal_planned_take_profit,
        "journal_stop_loss_basis": trade.journal_stop_loss_basis,
        "journal_confidence": trade.journal_confidence,
        "journal_anxiety": trade.journal_anxiety,
        "journal_followed_rule": trade.journal_followed_rule,
        "journal_emotion": trade.journal_emotion,
        "journal_pre_notes": trade.journal_pre_notes,
        "journal_exit_reason": trade.journal_exit_reason,
        "journal_as_expected": trade.journal_as_expected,
        "journal_improvement": trade.journal_improvement,
        "journal_post_notes": trade.journal_post_notes,
        "journal_rule_tags": _json.loads(trade.journal_rule_tags) if trade.journal_rule_tags else [],
        "is_precommitted": is_precommitted,
    }

    if trade.analysis_id:
        analysis = db.query(ChartAnalysis).filter(ChartAnalysis.id == trade.analysis_id).first()
        if analysis:
            trade_data["chart_analysis"] = {
                "trend": analysis.trend,
                "support_resistance": analysis.support_resistance,
                "dow_theory": analysis.dow_theory,
                "candle_pattern": analysis.candle_pattern,
                "moving_average": analysis.moving_average,
                "rsi_macd": analysis.rsi_macd,
                "volatility": analysis.volatility,
                "entry_reason": analysis.entry_reason,
                "risk_reward": analysis.risk_reward,
            }

    try:
        review = await asyncio.to_thread(claude_client.analyze_trade_review, trade_data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AIレビューでエラーが発生しました: {e}")

    trade.ai_review = _json.dumps(review, ensure_ascii=False)
    trade.ai_review_created_at = datetime.utcnow()
    db.commit()
    db.refresh(trade)

    return {"trade_id": trade.id, "review": review, "is_precommitted": is_precommitted}


def _serialize_trade(trade: Trade) -> dict:
    """journal_rule_tagsをJSON配列としてデコードし、利益率(%)も付与して返す"""
    from app.services.stats_calculator import _return_pct

    is_precommitted = bool(
        trade.journal_pre_committed_at and trade.exit_datetime
        and trade.journal_pre_committed_at < trade.exit_datetime
    )
    data = {c.name: getattr(trade, c.name) for c in trade.__table__.columns}
    try:
        data["journal_rule_tags"] = _json.loads(trade.journal_rule_tags) if trade.journal_rule_tags else []
    except (ValueError, TypeError):
        data["journal_rule_tags"] = []
    data["is_precommitted"] = is_precommitted
    return_pct = _return_pct(trade)
    data["return_pct"] = round(return_pct, 3) if return_pct is not None else None
    return data
