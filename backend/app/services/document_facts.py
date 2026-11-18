"""LLM이 틀리기 쉬운 날짜 계산을 코드로 처리한다."""

from __future__ import annotations

import re
from datetime import date
from typing import Dict, Optional


def _find_date(text: str, label: str) -> Optional[date]:
    m = re.search(
        label + r"[^\d]{0,12}((?:19|20)\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})",
        text.replace("|", " "),
    )
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def compute_document_facts(text: str) -> Dict[str, str]:
    start, end = _find_date(text, "입원일"), _find_date(text, "퇴원일")
    if start and end and end >= start:
        nights = (end - start).days
        if not nights:
            return {"입원기간": f"{start.month}월 {start.day}일 당일 입원·퇴원"}
        return {"입원기간": f"{start.month}월 {start.day}일부터 {end.month}월 {end.day}일까지, {nights}박 {nights + 1}일"}
    return {}
