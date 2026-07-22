"""
FXトレード検証ツール バックエンド エントリーポイント
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import init_db
from app.api import (
    chart_analysis,
    trade_record,
    verification,
    statistics,
    improvement,
    admin,
)

app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 各機能のルーターを登録
app.include_router(chart_analysis.router)
app.include_router(trade_record.router)
app.include_router(verification.router)
app.include_router(statistics.router)
app.include_router(improvement.router)
app.include_router(admin.router)


@app.on_event("startup")
def on_startup():
    os.makedirs("./data", exist_ok=True)
    init_db()


@app.get("/")
def root():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
