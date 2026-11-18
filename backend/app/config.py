"""환경 설정과 공통 기본값을 한 곳에서 관리한다 (코드 곳곳에 흩어진 기본값 방지)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_RAG_MIN_SCORE = 1.5

_SYSTEM_FONT_PATHS = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/malgun.ttf",
]


def openai_model() -> str:
    return (os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()


def rag_min_score() -> float:
    """이 점수 미만의 검색 결과는 관련 없는 자료로 보고 버린다."""
    try:
        return float(os.getenv("RAG_MIN_SCORE", DEFAULT_RAG_MIN_SCORE))
    except ValueError:
        return DEFAULT_RAG_MIN_SCORE


def korean_font_candidates() -> List[str]:
    """MEDIHAN_FONT_PATH 환경변수를 우선하고, 그다음 OS별 일반 경로를 본다."""
    custom = (os.getenv("MEDIHAN_FONT_PATH") or "").strip()
    return ([custom] if custom else []) + _SYSTEM_FONT_PATHS


def first_existing_font() -> str | None:
    for path in korean_font_candidates():
        if Path(path).exists():
            return path
    return None
