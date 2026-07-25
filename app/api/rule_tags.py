"""
ルールタグライブラリAPI
事前記録で使う取引ルールタグを、カテゴリ別に取得・追加・削除する。
"""
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import RuleTag

router = APIRouter(prefix="/api/rule-tags", tags=["rule-tags"])


class RuleTagCreate(BaseModel):
    category: str
    name: str


@router.get("/")
def list_rule_tags(db: Session = Depends(get_db)):
    """カテゴリ別にグループ化したルールタグ一覧を返す"""
    tags = db.query(RuleTag).order_by(RuleTag.category, RuleTag.id).all()
    grouped = defaultdict(list)
    for t in tags:
        grouped[t.category].append({"id": t.id, "name": t.name})
    return grouped


@router.post("/")
def create_rule_tag(tag_in: RuleTagCreate, db: Session = Depends(get_db)):
    """新しいルールタグを追加する(カテゴリが無ければ新規カテゴリとして扱う)"""
    existing = db.query(RuleTag).filter(
        RuleTag.category == tag_in.category, RuleTag.name == tag_in.name
    ).first()
    if existing:
        return existing

    tag = RuleTag(category=tag_in.category, name=tag_in.name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/{tag_id}")
def delete_rule_tag(tag_id: int, db: Session = Depends(get_db)):
    """ルールタグを削除する"""
    tag = db.query(RuleTag).filter(RuleTag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="タグが見つかりません")
    db.delete(tag)
    db.commit()
    return {"status": "deleted"}
