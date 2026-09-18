"""관리 API 진입점."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adminapi.routers import assets, auth, editing, health, jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="recording4 관리 API",
    version="0.1.0",
    description=(
        "원본 등록, 작업 생성, 상태 조회. "
        "브라우저에는 저장소·AI·YouTube 자격증명을 전달하지 않습니다."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(assets.router)
app.include_router(jobs.router)

app.include_router(editing.router)
