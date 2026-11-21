"""Medihan FastAPI 백엔드 서버."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.graph import MEDIHAN_GRAPH
from app.config import DEFAULT_OPENAI_MODEL
from app.services.hospital_search import (
    HospitalSearchError,
    search_hospitals as search_kakao_hospitals,
)
from app.services.health_criteria import evaluate_metrics
from app.services.ocr_masking import process_document
from app.services.rag_service import RAG_SERVICE
from app.services.kdca_api import (
    KDCAApiError,
    fetch_kdca_content,
)
from app.services.report_exporter import REPORTS_DIR, generate_reports_bundle
from app.services.download_links import cleanup_report_files, verify_download_token
from app.services.upload_validation import (
    MAX_UPLOAD_BYTES,
    iter_pdf_page_files,
    validate_upload,
)

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

for _name in ("OPENAI_API_KEY", "OPENAI_MODEL"):
    if not os.getenv(_name):
        for _key, _value in os.environ.items():
            if _key.upper() == _name and _value.strip():
                os.environ[_name] = _value.strip()
                break

RUNTIME_CONFIG: Dict[str, str] = {
    "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
    "openai_model": os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip(),
}

# EasyOCR 인스턴스의 동시 초기화·공유 추론 충돌을 피한다. 실서비스에서는 작업 큐로 확장.
OCR_PROCESS_LOCK = Lock()

app = FastAPI(title="Medihan API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("MEDIHAN_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def on_startup() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_report_files(REPORTS_DIR)
    api_key = RUNTIME_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "").strip()
    RAG_SERVICE.ensure_indexed(force=False, api_key=api_key)


class ApiKeyRequest(BaseModel):
    api_key: str
    model: Optional[str] = None


class ChatRequest(BaseModel):
    user_message: str = ""
    action_type: str = "auto"
    location: str = ""
    gender: str = "unknown"
    metrics: Dict[str, Any] = Field(default_factory=dict)
    safe_text: str = ""
    chat_history: List[Dict[str, str]] = Field(default_factory=list)


class ExportRequest(BaseModel):
    metrics: Dict[str, Any] = Field(default_factory=dict)
    gender: str = "unknown"
    summary_text: str = ""
    rag_sources: List[Dict[str, Any]] = Field(default_factory=list)
    hospitals: List[Dict[str, Any]] = Field(default_factory=list)
    formats: List[str] = Field(default_factory=lambda: ["docx", "pdf", "png"])


class HospitalRequest(BaseModel):
    departments: List[str] = []
    location: str = ""

    latitude: Optional[float] = None
    longitude: Optional[float] = None

    radius: int = 5000

def _mask_key_preview(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "****"
    return f"{key[:5]}...{key[-4:]}"


@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    key = RUNTIME_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "").strip()
    return {
        "status": "ok",
        "openai_configured": bool(key),
        "openai_key_preview": _mask_key_preview(key),
        "model": RUNTIME_CONFIG.get("openai_model", DEFAULT_OPENAI_MODEL),
    }


@app.post("/api/SetApiKey")
def set_api_key(req: ApiKeyRequest) -> Dict[str, Any]:
    # 서버 전역 API 키 변경은 명시적인 로컬 개발 모드에서만 사용한다.
    # 공개 서비스에서는 이 API를 비활성화하고 서버 환경변수/비밀관리자로 설정한다.
    if os.getenv("MEDIHAN_ALLOW_RUNTIME_API_KEY", "false").strip().lower() != "true":
        raise HTTPException(status_code=403, detail="런타임 API 키 변경이 비활성화되어 있습니다. 서버의 .env를 사용하세요.")
    key = req.api_key.strip()
    RUNTIME_CONFIG["openai_api_key"] = key
    if key:
        os.environ["OPENAI_API_KEY"] = key
    else:
        os.environ.pop("OPENAI_API_KEY", None)
    if req.model:
        RUNTIME_CONFIG["openai_model"] = req.model.strip()
        os.environ["OPENAI_MODEL"] = req.model.strip()
    return {
        "openai_configured": bool(key),
        "openai_key_preview": _mask_key_preview(key),
        "model": RUNTIME_CONFIG.get("openai_model", DEFAULT_OPENAI_MODEL),
    }


@app.get("/api/rag/status")
def rag_status() -> Dict[str, Any]:
    api_key = RUNTIME_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "").strip()
    return RAG_SERVICE.get_status(api_key=api_key)

@app.get("/api/kdca/content/{content_id}")
def kdca_content(content_id: str) -> Dict[str, Any]:
    # 인증 없는 개발 환경의 시험용 API.
    # 실서비스 공개 전에는 사용자 인증과 요청 제한 필요.
    if (
        os.getenv(
            "MEDIHAN_KDCA_PREVIEW_ENABLED",
            "false",
        ).lower() != "true"
    ):
        raise HTTPException(
            status_code=403,
            detail="KDCA 시험 조회 기능이 비활성화되어 있습니다.",
        )

    try:
        return fetch_kdca_content(content_id)

    except KDCAApiError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc

@app.post("/api/rag/reindex")
def rag_reindex() -> Dict[str, Any]:
    if os.getenv("MEDIHAN_ALLOW_RAG_REINDEX", "false").strip().lower() != "true":
        raise HTTPException(status_code=403, detail="RAG 수동 색인이 비활성화되어 있습니다.")
    api_key = RUNTIME_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "").strip()
    count = RAG_SERVICE.ensure_indexed(force=True, api_key=api_key)
    status = RAG_SERVICE.get_status(api_key=api_key)
    status["reindexed_chunks"] = count
    return status


def _preprocess_all_pages(
    file_bytes: bytes,
    filename: str,
    mask_name: bool,
    mask_rrn: bool,
    mask_age: bool,
    mask_contact: bool,
) -> Dict[str, Any]:
    """서버 사이드 파일 검증 후 페이지별로 OCR과 자동 마스킹을 실행한다."""
    info = validate_upload(file_bytes, filename)
    kwargs = dict(mask_name=mask_name, mask_rrn=mask_rrn, mask_age=mask_age, mask_contact=mask_contact)

    with OCR_PROCESS_LOCK:
        if info.kind == "pdf":
            results = [process_document(page, f"page_{n}.pdf", **kwargs)
                       for n, page in enumerate(iter_pdf_page_files(file_bytes), start=1)]
        else:
            results = [process_document(file_bytes, info.filename, **kwargs)]

    # 기존 프런트엔드 호환을 위해 첫 페이지 이미지 키는 그대로 유지한다.
    merged = dict(results[0])
    merged["page_count"] = len(results)
    merged["pages"] = [
        {
            "page": index,
            "original_image": result["original_image"],
            "masked_image": result["masked_image"],
            "masked_count": result["masked_count"],
        }
        for index, result in enumerate(results, start=1)
    ]
    merged["safe_text"] = "\n\n".join(
        f"[페이지 {index}]\n{result['safe_text']}"
        for index, result in enumerate(results, start=1)
    )
    merged["masked_items"] = [
        {**item, "page": index}
        for index, result in enumerate(results, start=1)
        for item in result["masked_items"]
    ]
    merged["masked_count"] = len(merged["masked_items"])
    merged["detected_pii_candidates"] = sum(result["detected_pii_candidates"] for result in results)
    merged["metrics"] = {k: v for result in results for k, v in result["metrics"].items()}
    merged["gender"] = next((result["gender"] for result in results if result["gender"] != "unknown"), "unknown")
    return merged


@app.post("/api/preprocess")
async def preprocess_document(
    file: UploadFile = File(...),
    mask_name: bool = Form(default=True),
    mask_rrn: bool = Form(default=True),
    mask_age: bool = Form(default=True),
    mask_contact: bool = Form(default=True),
) -> Dict[str, Any]:
    # UploadFile.read()에 제한을 두어 과도한 파일을 메모리로 끝없이 읽지 않도록 한다.
    try:
        file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
        return await asyncio.to_thread(
            _preprocess_all_pages,
            file_bytes,
            file.filename or "upload.png",
            mask_name, mask_rrn, mask_age, mask_contact,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("문서 전처리 실패")
        raise HTTPException(status_code=500, detail="문서 처리 중 오류가 발생했습니다.") from exc
    finally:
        await file.close()


@app.post("/api/chat")
def run_chat(req: ChatRequest) -> Dict[str, Any]:
    api_key = RUNTIME_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "").strip()
    initial_state: Dict[str, Any] = {
        "user_message": req.user_message,
        "action_type": req.action_type,
        "location": req.location,
        "gender": req.gender,
        "metrics": req.metrics,
        "safe_text": req.safe_text,
        "chat_history": req.chat_history,
        "api_key": api_key,
        "executed_nodes": [],
    }
    final_state = MEDIHAN_GRAPH.invoke(initial_state)
    return {
        "assistant_reply": final_state.get("assistant_reply", ""),
        "llm_mode": final_state.get("llm_mode", ""),
        "llm_error": final_state.get("llm_error", ""),
        "intent": final_state.get("intent", "chat"),
        "metrics": final_state.get("metrics", req.metrics),
        "evaluations": final_state.get("evaluations", []),
        "recommended_departments": final_state.get("recommended_departments", []),
        "confirm_exam_eligible": final_state.get("confirm_exam_eligible", []),
        "rag_sources": final_state.get("rag_sources", []),
        "policy_results": final_state.get("policy_results", {}),
        "hospitals": final_state.get("hospitals", []),
        "hospital_notice": final_state.get("hospital_notice", ""),
        "report_files": final_state.get("report_files", {}),
        "open_right_panel": final_state.get("open_right_panel", False),
        "right_panel_tab": final_state.get("right_panel_tab", "reports"),
    }


@app.post("/api/hospitals")
def search_hospitals(req: HospitalRequest) -> Dict[str, Any]:
    try:
        return search_kakao_hospitals(
            departments=req.departments,
            location=req.location,
            latitude=req.latitude,
            longitude=req.longitude,
            radius=req.radius,
        )

    except HospitalSearchError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc

@app.post("/api/export")
def export_reports(req: ExportRequest) -> Dict[str, Any]:
    allowed_formats = {"docx", "pdf", "png"}
    if not req.formats or any(fmt not in allowed_formats for fmt in req.formats):
        raise HTTPException(status_code=400, detail="지원하지 않는 보고서 형식입니다.")
    eval_res = evaluate_metrics(req.metrics, gender=req.gender)
    payload = {
        "evaluations": eval_res.get("evaluations", []),
        "summary_text": req.summary_text,
        "rag_sources": req.rag_sources,
        "hospitals": req.hospitals,
    }
    files = generate_reports_bundle(payload, formats=req.formats)
    return {"files": files}


@app.get("/api/download/{filename}")
def download_report(filename: str, token: str = Query(default="")):
    safe_name = Path(filename).name
    if not verify_download_token(safe_name, token):
        raise HTTPException(status_code=403, detail="다운로드 링크가 없거나 만료되었습니다.")
    target = (REPORTS_DIR / safe_name).resolve()
    if target.parent != REPORTS_DIR.resolve() or not target.is_file():
        raise HTTPException(status_code=404, detail="요청한 보고서 파일을 찾을 수 없습니다.")
    return FileResponse(path=str(target), filename=safe_name)
