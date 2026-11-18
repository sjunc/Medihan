"""지식베이스의 사전형 문서(`## 용어 | 별칭 | 코드` 제목줄)를 서류 텍스트에서 정확 조회한다."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.services.kcd_lookup import find_codes

KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"
_CODE_FIELD = re.compile(r"^[A-Z]\d{2}(?:\.?\d{1,2})?$")
_MIN_ALIAS_LEN = 2


def _squash(text: str) -> str:
    return re.sub(r"[\s|]+", "", text)


@lru_cache(maxsize=1)
def _load_entries() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for path in sorted(KNOWLEDGE_BASE_DIR.glob("*.md")):
        current: Dict[str, Any] | None = None
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("## "):
                fields = [f.strip() for f in line[3:].split("|")]
                code = ""
                if len(fields) > 1 and _CODE_FIELD.match(fields[-1]):
                    code = fields.pop().replace(".", "")
                names = [fields[0]] + [a.strip() for a in (fields[1].split(",") if len(fields) > 1 else []) if a.strip()]
                current = {"term": fields[0], "names": names, "code": code, "details": {}, "source": path.name}
                if len(fields) > 1 or code:
                    entries.append(current)
                else:
                    current = None
            elif current is not None and line.startswith("- ") and ":" in line:
                key, _, value = line[2:].partition(":")
                current["details"][key.strip()] = value.strip()
    return entries


def lookup_glossary(text: str) -> List[Dict[str, Any]]:
    """서류에 등장한 용어·질병코드와 일치하는 사전 항목을 돌려준다."""
    squashed = _squash(text)
    doc_codes = find_codes(text)
    hits: List[Dict[str, Any]] = []
    for entry in _load_entries():
        by_name = any(len(n) >= _MIN_ALIAS_LEN and _squash(n) in squashed for n in entry["names"])
        by_code = bool(entry["code"]) and any(c.startswith(entry["code"]) for c in doc_codes)
        if by_name or by_code:
            hits.append(
                {
                    "term": entry["term"],
                    "matched_by": "질병코드" if by_code and not by_name else "용어 일치",
                    "details": entry["details"],
                    "source": entry["source"],
                }
            )
    return hits
