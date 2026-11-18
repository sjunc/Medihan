"""로컬 OCR(EasyOCR) + 라이브러리 기반 개인정보 자동 마스킹(OpenCV/Pillow) 모듈."""

from __future__ import annotations

import base64
import io
import re
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

from app.config import first_existing_font

_OCR_READER = None

def get_korean_font_path() -> Optional[str]:
    """사용 가능한 한글 폰트 파일 경로를 반환한다(MEDIHAN_FONT_PATH 환경변수로 지정 가능)."""
    return first_existing_font()


def _ensure_lzma_stub() -> None:
    """pyenv Python 빌드에 _lzma C 확장이 누락된 경우 torchvision/easyocr 임포트용 호환 스텁을 등록한다."""
    try:
        import lzma  # noqa: F401
        return
    except Exception:
        pass

    class LZMAError(Exception):
        pass

    class LZMACompressor:
        def __init__(self, *args, **kwargs):
            pass

        def compress(self, data: bytes) -> bytes:
            return data

        def flush(self) -> bytes:
            return b""

    class LZMADecompressor:
        def __init__(self, *args, **kwargs):
            self.eof = True
            self.needs_input = False

        def decompress(self, data: bytes, max_length: int = -1) -> bytes:
            return data

    class LZMAFile:
        def __init__(self, *args, **kwargs):
            raise LZMAError("_lzma C 확장이 없는 환경입니다.")

    stub = types.ModuleType("lzma")
    stub.LZMAError = LZMAError  # type: ignore[attr-defined]
    stub.LZMACompressor = LZMACompressor  # type: ignore[attr-defined]
    stub.LZMADecompressor = LZMADecompressor  # type: ignore[attr-defined]
    stub.LZMAFile = LZMAFile  # type: ignore[attr-defined]
    stub.FORMAT_AUTO = 0  # type: ignore[attr-defined]
    stub.FORMAT_XZ = 1  # type: ignore[attr-defined]
    stub.FORMAT_ALONE = 2  # type: ignore[attr-defined]
    stub.FORMAT_RAW = 3  # type: ignore[attr-defined]
    stub.CHECK_NONE = 0  # type: ignore[attr-defined]
    stub.CHECK_CRC32 = 1  # type: ignore[attr-defined]
    stub.CHECK_CRC64 = 4  # type: ignore[attr-defined]
    stub.CHECK_SHA256 = 10  # type: ignore[attr-defined]
    stub.FILTER_LZMA1 = 0x4000000000000001  # type: ignore[attr-defined]
    stub.FILTER_LZMA2 = 0x21  # type: ignore[attr-defined]
    stub.PRESET_DEFAULT = 6  # type: ignore[attr-defined]
    stub.PRESET_EXTREME = 1 << 31  # type: ignore[attr-defined]
    stub.is_check_supported = lambda _check: False  # type: ignore[attr-defined]
    stub.open = lambda *args, **kwargs: LZMAFile(*args, **kwargs)  # type: ignore[attr-defined]
    stub.compress = lambda data, *args, **kwargs: data  # type: ignore[attr-defined]
    stub.decompress = lambda data, *args, **kwargs: data  # type: ignore[attr-defined]

    sys.modules["_lzma"] = stub
    sys.modules["lzma"] = stub


def get_ocr_reader():
    """EasyOCR 한국어/영어 리더 싱글톤을 지연 로딩한다."""
    global _OCR_READER
    if _OCR_READER is None:
        _ensure_lzma_stub()
        import easyocr

        _OCR_READER = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    return _OCR_READER


def _image_bytes_to_bgr(file_bytes: bytes, filename: str) -> np.ndarray:
    """PDF 또는 이미지 바이트를 OpenCV BGR ndarray로 변환한다."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if len(doc) == 0:
            raise ValueError("빈 PDF 파일입니다.")
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        pil_img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return bgr


def _bgr_to_base64_png(bgr: np.ndarray) -> str:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _box_bounds(bbox: List[List[float]]) -> Tuple[int, int, int, int]:
    xs = [int(pt[0]) for pt in bbox]
    ys = [int(pt[1]) for pt in bbox]
    return min(xs), min(ys), max(xs), max(ys)


PLACEHOLDER = "[개인정보_마스킹됨]"

# 값이 라벨 오른쪽 칸에 있는 서식(진단서·소견서·검진표 등)을 대상으로 한다.
_PII_LABELS: Dict[str, Tuple[str, ...]] = {
    "name": ("환자성명", "수검자명", "환자명", "성명", "이름"),
    "rrn": ("주민등록번호", "주민번호", "환자등록번호", "등록번호"),
    "age": ("생년월일", "연령", "나이"),
    "contact": ("휴대전화", "전화번호", "연락처", "주소"),
}
# 값 추적을 멈추는 일반 서식 라벨 (진단·치료 내용이 개인정보로 오인되지 않도록 경계 역할)
_STOP_LABELS: Tuple[str, ...] = (
    "성별", "병명", "진단명", "질병명", "상병", "발병일", "진단일", "진료일", "치료내용", "치료기간",
    "소견", "향후치료의견", "용도", "비고", "의사", "면허번호", "의료기관", "직업", "국적", "작성일",
    "발행일", "검진일", "검진유형", "수술일", "입원", "퇴원", "구분", "처방", "약품명",
)

_MASK_CHARS = r"\d\*●○•xX"
_RRN_FULL = re.compile(rf"(?<!\d)\d{{6}}\s*[-~–_]\s*[1-4{_MASK_CHARS[3:]}][{_MASK_CHARS}]{{0,6}}|(?<!\d)\d{{6}}[1-4]\d{{6}}(?!\d)")
_RRN_TAIL = re.compile(rf"[-~–_]\s*[1-4{_MASK_CHARS[3:]}][{_MASK_CHARS}]{{5,6}}")
_RRN_TAIL_LOOSE = re.compile(rf"[-~–_]?\s*[1-4{_MASK_CHARS[3:]}][{_MASK_CHARS}]{{5,6}}")
_RRN_CHARS = re.compile(r"[\d\-~–_.*●○•xX\s]+")
_PHONE = re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}|0\d{1,2}[-\s.]\d{3,4}[-\s.]\d{4}")
_ADDRESS = re.compile(
    r"^(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"\S{0,6}\s*\S{1,8}?(?:시|군|구)\s*\S*\s*.*?(?:로|길|동|읍|면|리)\s*\d"
)
_AGE_SHORT = re.compile(r"(?:만\s*)?\d{1,3}\s*세")
_AGE_CHARS = re.compile(r"[\d.\-/년월일세만\s]+")


def _compact(text: str) -> str:
    return re.sub(r"[\s:：|]", "", text)


def _match_label(text: str) -> Optional[Tuple[str, str, Optional[int]]]:
    """토큰이 개인정보 라벨로 시작하면 (카테고리, 라벨, 같은 칸 값 시작 위치)를 반환한다."""
    chars = [(i, c) for i, c in enumerate(text) if not c.isspace() and c not in ":：|"]
    compact = "".join(c for _, c in chars)
    for cat, keywords in _PII_LABELS.items():
        for kw in keywords:
            if not compact.startswith(kw):
                continue
            if len(compact) == len(kw):
                return cat, kw, None
            pos = chars[len(kw) - 1][0] + 1
            while pos < len(text) and (text[pos].isspace() or text[pos] in ":：|"):
                pos += 1
            return cat, kw, (pos if pos < len(text) else None)
    return None


def _is_label_token(text: str) -> bool:
    compact = _compact(text)
    labels = [kw for kws in _PII_LABELS.values() for kw in kws] + list(_STOP_LABELS)
    return any(compact.startswith(kw) and len(compact) <= len(kw) + 2 for kw in labels)


def _group_rows(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OCR 박스를 줄 단위로 묶고 줄 안에서는 왼쪽→오른쪽으로 정렬한다."""
    if not items:
        return items
    heights = sorted(it["bounds"][3] - it["bounds"][1] for it in items)
    tol = max(0.6 * (heights[len(heights) // 2] or 20), 8)
    rows: List[Dict[str, Any]] = []
    for it in sorted(items, key=lambda i: (i["bounds"][1] + i["bounds"][3]) / 2):
        cy = (it["bounds"][1] + it["bounds"][3]) / 2
        if rows and abs(cy - rows[-1]["sum"] / len(rows[-1]["items"])) <= tol:
            rows[-1]["items"].append(it)
            rows[-1]["sum"] += cy
        else:
            rows.append({"sum": cy, "items": [it]})
    ordered: List[Dict[str, Any]] = []
    for row_no, row in enumerate(rows):
        for it in sorted(row["items"], key=lambda i: i["bounds"][0]):
            it["row"] = row_no
            ordered.append(it)
    return ordered


def _detect_pii_targets(ocr_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """줄 단위로 정렬된 OCR 결과에서 이름/주민번호/연령/연락처·주소 박스를 식별한다.

    치료내용 같은 의료 정보가 가려지지 않도록 라벨 기반 탐지를 우선하고,
    정규식은 형태가 뚜렷한 값(주민번호·전화번호·주소 시작 형태·짧은 나이 표기)에만 사용한다.
    """
    targets: Dict[int, Dict[str, Any]] = {}

    def add(idx: int, cat: str, label: str, text: str, bbox: Optional[List[List[float]]] = None, prefix: str = "") -> None:
        if idx not in targets:
            targets[idx] = {
                "idx": idx,
                "category": cat,
                "label": label,
                "text": text,
                "bbox": bbox or ocr_items[idx]["bbox"],
                "prefix": prefix,
            }

    # 1차: 라벨 기반 (같은 칸 값 / 같은 줄 오른쪽 값)
    for idx, item in enumerate(ocr_items):
        text = item["text"].strip()
        matched = _match_label(text)
        if not matched:
            continue
        cat, kw, value_start = matched
        x1, y1, x2, y2 = item["bounds"]

        if value_start is not None:
            split_x = int(x1 + (x2 - x1) * value_start / len(text))
            add(idx, cat, kw, text[value_start:], [[split_x, y1], [x2, y1], [x2, y2], [split_x, y2]], text[:value_start])
            continue

        height = max(y2 - y1, 24)
        prev_x2, taken = x2, 0
        for j in range(idx + 1, len(ocr_items)):
            cand = ocr_items[j]
            if cand["row"] != item["row"]:
                break
            cand_txt = cand["text"].strip()
            gap = cand["bounds"][0] - prev_x2
            if not cand_txt or _is_label_token(cand_txt) or _match_label(cand_txt):
                break
            if gap > (max(300, 10 * height) if taken == 0 else max(150, 5 * height)):
                break
            compact = _compact(cand_txt)
            if cat == "name" and (len(compact) > 5 or taken >= 2 or (taken == 1 and gap > 1.2 * height)):
                break
            if cat == "rrn" and (taken >= 3 or not _RRN_CHARS.fullmatch(cand_txt)):
                break
            if cat == "age" and (taken >= 3 or not _AGE_CHARS.fullmatch(cand_txt)):
                break
            if cat == "contact" and taken >= 4:
                break
            add(j, cat, kw, cand_txt)
            prev_x2, taken = cand["bounds"][2], taken + 1

    # 2차: 형태가 뚜렷한 값 (라벨이 인식되지 않은 경우 보완)
    for idx, item in enumerate(ocr_items):
        text = item["text"].strip()
        if _RRN_FULL.search(text) or _RRN_TAIL.fullmatch(text):
            add(idx, "rrn", "주민등록번호", text)
        elif _PHONE.search(text):
            add(idx, "contact", "연락처", text)
        elif _ADDRESS.match(text):
            add(idx, "contact", "주소", text)
        elif _AGE_SHORT.fullmatch(text):
            add(idx, "age", "연령", text)

    # OCR이 주민번호를 앞 6자리 / 뒷자리로 나눠 읽은 경우 두 조각 모두 가린다
    for idx, item in enumerate(ocr_items[:-1]):
        nxt = ocr_items[idx + 1]
        if (
            re.fullmatch(r"\d{6}", item["text"].strip())
            and nxt["row"] == item["row"]
            and nxt["bounds"][0] - item["bounds"][2] <= max(80, 3 * (item["bounds"][3] - item["bounds"][1]))
            and _RRN_TAIL_LOOSE.fullmatch(nxt["text"].strip())
        ):
            add(idx, "rrn", "주민등록번호", item["text"].strip())
            add(idx + 1, "rrn", "주민등록번호", nxt["text"].strip())

    return list(targets.values())


def _apply_mask_boxes(
    bgr: np.ndarray,
    targets: List[Dict[str, Any]],
    mask_options: Dict[str, bool],
) -> Tuple[np.ndarray, List[Dict[str, str]]]:
    """체크된 카테고리 항목만 이미지 위에 보안 마스킹 박스 처리한다."""
    masked = bgr.copy()
    applied_items: List[Dict[str, str]] = []

    for tgt in targets:
        cat = tgt["category"]
        if not mask_options.get(cat, True):
            continue
        x1, y1, x2, y2 = _box_bounds(tgt["bbox"])
        pad_x, pad_y = 6, 4
        rx1 = max(0, x1 - pad_x)
        ry1 = max(0, y1 - pad_y)
        rx2 = min(masked.shape[1], x2 + pad_x)
        ry2 = min(masked.shape[0], y2 + pad_y)

        cv2.rectangle(masked, (rx1, ry1), (rx2, ry2), (15, 23, 42), thickness=-1)
        cv2.rectangle(masked, (rx1, ry1), (rx2, ry2), (16, 185, 129), thickness=2)

        applied_items.append(
            {
                "category": cat,
                "label": tgt["label"],
                "masked_preview": _mask_text_preview(tgt["text"]),
            }
        )

    # PIL로 깔끔한 [MASKED] 배지 텍스트 렌더링
    if applied_items:
        rgb = cv2.cvtColor(masked, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        draw = ImageDraw.Draw(pil_img)
        font_path = get_korean_font_path()
        try:
            badge_font = ImageFont.truetype(font_path, 13) if font_path else ImageFont.load_default()
        except Exception:
            badge_font = ImageFont.load_default()

        for tgt in targets:
            if not mask_options.get(tgt["category"], True):
                continue
            x1, y1, x2, y2 = _box_bounds(tgt["bbox"])
            tag = "[MASKED]"
            tx = max(0, x1)
            ty = max(0, (y1 + y2) // 2 - 7)
            if (x2 - x1) >= 55:
                draw.text((tx + 4, ty), tag, fill=(110, 231, 183), font=badge_font)
        masked = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    return masked, applied_items


def _mask_text_preview(text: str) -> str:
    return "*" * max(2, min(len(text), 8))


def _scrub_text(text: str, mask_options: Dict[str, bool]) -> str:
    """OCR 박스 탐지가 놓친 주민번호·전화번호를 최종 텍스트에서 한 번 더 제거한다."""
    if mask_options.get("rrn", True):
        text = _RRN_FULL.sub(PLACEHOLDER, text)
    if mask_options.get("contact", True):
        text = _PHONE.sub(PLACEHOLDER, text)
    return text


def extract_health_metrics(text: str) -> Dict[str, Any]:
    """OCR 텍스트 또는 사용자 직접 입력 텍스트에서 주요 건강검진 수치를 정규화 추출한다."""
    metrics: Dict[str, Any] = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        lines = [text]

    def _parse_num(s: str) -> float | int:
        val = float(s.replace(",", "."))
        return int(val) if val.is_integer() else round(val, 1)

    for line in lines:
        clean = re.sub(r"(?<=\d),(?=\d{3}\b)", "", line)

        # 혈압 (148/92 또는 148 | 92)
        if "systolic_bp" not in metrics:
            bp_m = re.search(
                r"(?:혈[압합]|수축기|BP)?[^\d]{0,25}?(\d{2,3})\s*(?:/|\|)\s*(\d{2,3})\s*(?:mmn?Hg)?",
                clean,
                re.IGNORECASE,
            )
            if bp_m and ("혈" in clean or "BP" in clean.upper() or "mm" in clean.lower() or len(lines) <= 2):
                sbp, dbp = int(bp_m.group(1)), int(bp_m.group(2))
                if 70 <= sbp <= 260 and 40 <= dbp <= 160:
                    metrics["systolic_bp"] = sbp
                    metrics["diastolic_bp"] = dbp

        line_patterns = [
            ("fasting_glucose", r"(?:공[복북목부]\s*[혈철헬헐]?당|공복.{0,2}당|[혈철헬]당)\D{0,18}?(\d{2,3}(?:[.,]\d+)?)"),
            ("ldl_cholesterol", r"(?<![a-zA-Z])LDL(?![a-zA-Z])(?:\s*콜레스테롤|\s*.{0,5}레스.{0,4})?\D{0,18}?(\d{2,3}(?:[.,]\d+)?)"),
            ("hdl_cholesterol", r"(?<![a-zA-Z])HDL(?![a-zA-Z])(?:\s*콜레스테롤|\s*.{0,5}레스.{0,4})?\D{0,18}?(\d{2,3}(?:[.,]\d+)?)"),
            ("triglycerides", r"중성지방\D{0,18}?(\d{2,3}(?:[.,]\d+)?)"),
            ("ast", r"(?<![a-zA-Z])AST(?![a-zA-Z])(?:\s*\(SGOT\))?\D{0,18}?(\d{1,3}(?:[.,]\d+)?)"),
            ("alt", r"(?<![a-zA-Z])ALT(?![a-zA-Z])(?:\s*\(SGPT\))?\D{0,18}?(\d{1,3}(?:[.,]\d+)?)"),
            ("ggt", r"(?:감마\s*지티피|r-?GTP|γ-?GTP)\D{0,18}?(\d{1,3}(?:[.,]\d+)?)"),
            ("egfr", r"(?:eGFR|신사구체여과율)\D{0,20}?(\d{1,3}(?:[.,]\d+)?)"),
            ("hemoglobin", r"(?:혈색소|헤모글로빈|혈색스)\D{0,18}?(\d{1,2}(?:[.,]\d+)?)"),
            ("bmi", r"(?:체질량지수|(?<![a-zA-Z])BMI?(?![a-zA-Z]))\D{0,18}?(\d{1,2}(?:[.,]\d+)?)"),
        ]
        for key, pat in line_patterns:
            if key in metrics:
                continue
            m = re.search(pat, clean, re.IGNORECASE)
            if m:
                metrics[key] = _parse_num(m.group(1))

        if "total_cholesterol" not in metrics and not re.search(r"(?<![a-zA-Z])(?:LDL|HDL)(?![a-zA-Z])", clean, re.IGNORECASE):
            tc_m = re.search(
                r"(?:총\s*콜레스테롤|총.{0,5}레스트?.{0,3}|콜레스테롤)\D{0,18}?(\d{2,3}(?:[.,]\d+)?)",
                clean,
                re.IGNORECASE,
            )
            if tc_m:
                metrics["total_cholesterol"] = _parse_num(tc_m.group(1))

    return metrics


def process_document(
    file_bytes: bytes,
    filename: str = "upload.png",
    mask_name: bool = True,
    mask_rrn: bool = True,
    mask_age: bool = True,
    mask_contact: bool = True,
) -> Dict[str, Any]:
    """업로드된 건강검진 결과지(PDF/이미지)에 대해 로컬 OCR 및 선택적 기본 마스킹을 수행한다."""
    if not file_bytes:
        raise ValueError("분석할 파일이 필요합니다.")

    bgr = _image_bytes_to_bgr(file_bytes, filename)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    ocr_items: List[Dict[str, Any]] = []
    ocr_engine = "Local OCR"

    reader = get_ocr_reader()
    raw_results = reader.readtext(rgb, detail=1, paragraph=False)
    for bbox, text, conf in raw_results:
        cleaned = str(text).strip()
        if not cleaned:
            continue
        bounds = _box_bounds(bbox)
        ocr_items.append(
            {
                "bbox": [[float(p[0]), float(p[1])] for p in bbox],
                "bounds": bounds,
                "text": cleaned,
                "conf": round(float(conf), 3),
            }
        )

    ocr_items = _group_rows(ocr_items)

    targets = _detect_pii_targets(ocr_items)
    mask_options = {
        "name": mask_name,
        "rrn": mask_rrn,
        "age": mask_age,
        "contact": mask_contact,
    }
    masked_bgr, applied_items = _apply_mask_boxes(bgr, targets, mask_options)

    # 마스킹된 칸만 플레이스홀더로 바꾸고 나머지 의료 내용은 그대로 둔다
    replacements = {
        t["idx"]: f"{t['prefix']}{PLACEHOLDER}" for t in targets if mask_options.get(t["category"], True)
    }
    rows: Dict[int, List[str]] = {}
    for idx, item in enumerate(ocr_items):
        rows.setdefault(item["row"], []).append(replacements.get(idx, item["text"]))
    safe_text = _scrub_text("\n".join(" | ".join(tokens) for _, tokens in sorted(rows.items())), mask_options)
    metrics = extract_health_metrics(safe_text)

    gender = "unknown"
    if re.search(r"성별\s*[:|]?\s*남|(?<![가-힣])남성(?![가-힣])|\|\s*남\s*(?:\||$)", safe_text):
        gender = "male"
    elif re.search(r"성별\s*[:|]?\s*여|(?<![가-힣])여성(?![가-힣])|\|\s*여\s*(?:\||$)", safe_text):
        gender = "female"

    return {
        "ocr_engine": ocr_engine,
        "original_image": _bgr_to_base64_png(bgr),
        "masked_image": _bgr_to_base64_png(masked_bgr),
        "masked_items": applied_items,
        "masked_count": len(applied_items),
        "safe_text": safe_text,
        "metrics": metrics,
        "gender": gender,
        "detected_pii_candidates": len(targets),
    }
