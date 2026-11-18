"""KCD-9 상병마스터 xlsx -> app/data/kcd9_codes.json (코드 -> 공식명/별칭/영문명). 마스터 파일 갱신 시 1회 실행."""
import json
import sys
from pathlib import Path

import openpyxl

BASE = Path(__file__).resolve().parents[1]
SRC = next((BASE / "knowledge_base").glob("*kcd9*.xlsx"), None)
OUT = BASE / "app" / "data" / "kcd9_codes.json"
MAX_ALIASES = 2

if SRC is None:
    sys.exit("knowledge_base에 KCD9 xlsx 파일이 없습니다.")

sheet = openpyxl.load_workbook(SRC, read_only=True).worksheets[0]  # 상병분류기호(전체)
table: dict = {}
for row in sheet.iter_rows(values_only=True):
    code, name, english = (str(c).strip() if c else "" for c in row[1:4])
    if not code or not name or code == "상병기호":
        continue
    entry = table.setdefault(code, {"name": name, "aliases": [], "en": english})
    if name != entry["name"] and name not in entry["aliases"] and len(entry["aliases"]) < MAX_ALIASES:
        entry["aliases"].append(name)

OUT.write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"{len(table)}개 코드 -> {OUT} ({OUT.stat().st_size // 1024}KB)")
