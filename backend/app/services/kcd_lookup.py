"""KCD-9 질병코드 정확 조회 (scripts/build_kcd9_lookup.py가 만든 app/data/kcd9_codes.json 사용)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

KCD9_JSON = Path(__file__).resolve().parents[1] / "data" / "kcd9_codes.json"
# 서류의 코드는 점 없이(K353) 적히지만 점이 있어도(K35.3) 같은 코드로 본다
_CODE_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])([A-Z]\d{2}(?:\.?\d{1,2})?)(?![A-Za-z0-9])")


@lru_cache(maxsize=1)
def _load_table() -> Dict[str, Dict[str, Any]]:
    if not KCD9_JSON.exists():
        return {}
    return json.loads(KCD9_JSON.read_text(encoding="utf-8"))


def find_codes(text: str) -> List[str]:
    """서류 텍스트에서 점 없는 형태로 정규화한 질병코드 후보를 등장 순서대로 돌려준다."""
    seen: List[str] = []
    for m in _CODE_IN_TEXT.finditer(text):
        code = m.group(1).replace(".", "")
        if code not in seen:
            seen.append(code)
    return seen


def lookup_kcd_codes(text: str) -> Dict[str, List[Any]]:
    """서류 텍스트에서 질병코드를 찾아 KCD-9 공식 명칭을 돌려준다. 표에 없는 코드는 unmatched_codes로 분리한다."""
    table = _load_table()
    codes: List[Dict[str, Any]] = []
    unmatched: List[str] = []
    seen = set()
    for m in _CODE_IN_TEXT.finditer(text):
        code = m.group(1).replace(".", "")
        if code in seen:
            continue
        seen.add(code)
        hit = table.get(code)
        if hit:
            codes.append({"code": code, **hit})
        else:
            unmatched.append(code)
    return {"codes": codes, "unmatched_codes": unmatched}
