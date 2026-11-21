"""업로드 크기·매직 바이트·확장자·페이지/이미지 해상도 검사.

클라이언트 검증은 사용성 목적이며 이 서버 검사가 최종 방어선이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterator

import pymupdf
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_RENDER_PIXELS = 18_000_000
PDF_RENDER_SCALE = 2.0  # ocr_masking._image_bytes_to_bgr의 렌더링 배율과 일치

ALLOWED_IMAGE_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
}


@dataclass(frozen=True)
class UploadInfo:
    kind: str  # pdf / image
    pages: int
    filename: str


def validate_upload(file_bytes: bytes, filename: str) -> UploadInfo:
    """파일 이름만 믿지 않고 실제 구조·포맷·해상도까지 확인한다."""
    if not file_bytes:
        raise ValueError("빈 파일은 업로드할 수 없습니다.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError(f"파일은 최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB까지 업로드할 수 있습니다.")

    safe_name = Path(filename.replace("\\", "/")).name
    ext = Path(safe_name).suffix.lower()

    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF-"):
            raise ValueError("PDF 확장자와 실제 파일 형식이 일치하지 않습니다.")
        try:
            with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise ValueError("암호화된 PDF는 현재 지원하지 않습니다.")
                page_count = len(doc)
                if not 1 <= page_count <= MAX_PDF_PAGES:
                    raise ValueError(f"PDF는 1~{MAX_PDF_PAGES}페이지까지 업로드할 수 있습니다.")
                for page in doc:
                    rect = page.rect
                    w = round(rect.width * PDF_RENDER_SCALE)
                    h = round(rect.height * PDF_RENDER_SCALE)
                    if w <= 0 or h <= 0 or w * h > MAX_RENDER_PIXELS:
                        raise ValueError("PDF 페이지의 크기 또는 해상도가 처리 한도를 초과했습니다.")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("열 수 없는 PDF입니다. 파일이 손상되었는지 확인해 주세요.") from exc
        return UploadInfo("pdf", page_count, safe_name)

    if ext not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("PDF, PNG, JPG, JPEG, WEBP 파일만 지원합니다.")

    try:
        with Image.open(BytesIO(file_bytes)) as img:
            if img.format != ALLOWED_IMAGE_FORMATS[ext]:
                raise ValueError("파일 확장자와 실제 이미지 형식이 일치하지 않습니다.")
            w, h = img.size
            if w <= 0 or h <= 0 or w * h > MAX_RENDER_PIXELS:
                raise ValueError("이미지 해상도가 처리 한도를 초과했습니다.")
            img.verify()
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("이미지를 읽을 수 없습니다. 파일이 손상되었는지 확인해 주세요.") from exc

    return UploadInfo("image", 1, safe_name)


def iter_pdf_page_files(file_bytes: bytes) -> Iterator[bytes]:
    """기존 1페이지 전용 OCR 코드를 재사용하도록 PDF를 페이지별로 분리한다."""
    with pymupdf.open(stream=file_bytes, filetype="pdf") as source:
        for page_number in range(len(source)):
            with pymupdf.open() as single:
                single.insert_pdf(source, from_page=page_number, to_page=page_number)
                yield single.tobytes(garbage=3, deflate=True)
