"""Medihan FastAPI 백엔드 서버."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agent.graph import MEDIHAN_GRAPH
from app.agent.tools import recommend_specialist_hospitals_tool
from app.config import DEFAULT_OPENAI_MODEL
from app.services.health_criteria import evaluate_metrics
from app.services.ocr_masking import process_document
from app.services.rag_service import RAG_SERVICE
from app.services.report_exporter import REPORTS_DIR, generate_reports_bundle

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

# .env 변수명이 소문자(openai_api_key)여도 인식되도록 대문자 환경변수로 맞춰 준다
for _name in ("OPENAI_API_KEY", "OPENAI_MODEL"):
    if not os.getenv(_name):
        for _k, _v in os.environ.items():
            if _k.upper() == _name and _v.strip():
                os.environ[_name] = _v.strip()
                break

RUNTIME_CONFIG: Dict[str, str] = {
    "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
    "openai_model": os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip(),
}

app = FastAPI(title="Medihan API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """서버 기동 시 지식베이스 인덱싱과 리포트 디렉토리를 준비한다."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
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
    metrics: Dict[str, Any] = {}
    safe_text: str = ""
    chat_history: List[Dict[str, str]] = []


class ExportRequest(BaseModel):
    metrics: Dict[str, Any] = {}
    gender: str = "unknown"
    summary_text: str = ""
    rag_sources: List[Dict[str, Any]] = []
    hospitals: List[Dict[str, Any]] = []
    formats: List[str] = ["docx", "pdf", "png"]


class HospitalRequest(BaseModel):
    departments: List[str] = []
    location: str = ""


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
    key = req.api_key.strip()
    RUNTIME_CONFIG["openai_api_key"] = key
    if key:
        os.environ["OPENAI_API_KEY"] = key
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


@app.post("/api/rag/reindex")
def rag_reindex() -> Dict[str, Any]:
    api_key = RUNTIME_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "").strip()
    count = RAG_SERVICE.ensure_indexed(force=True, api_key=api_key)
    status = RAG_SERVICE.get_status(api_key=api_key)
    status["reindexed_chunks"] = count
    return status


@app.post("/api/preprocess")
async def preprocess_document(
    file: UploadFile = File(...),
    mask_name: bool = Form(default=True),
    mask_rrn: bool = Form(default=True),
    mask_age: bool = Form(default=True),
    mask_contact: bool = Form(default=True),
) -> Dict[str, Any]:
    try:
        file_bytes = await file.read()
        filename = file.filename or "upload.png"
        result = process_document(
            file_bytes=file_bytes,
            filename=filename,
            mask_name=mask_name,
            mask_rrn=mask_rrn,
            mask_age=mask_age,
            mask_contact=mask_contact,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 처리 중 오류가 발생했습니다: {exc}") from exc


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
    raw = recommend_specialist_hospitals_tool.invoke(
        {"departments_csv": ",".join(req.departments), "location": req.location}
    )
    return json.loads(raw)


@app.post("/api/export")
def export_reports(req: ExportRequest) -> Dict[str, Any]:
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
def download_report(filename: str):
    safe_name = Path(filename).name
    target = (REPORTS_DIR / safe_name).resolve()
    if target.parent != REPORTS_DIR.resolve() or not target.exists():
        raise HTTPException(status_code=404, detail="요청한 보고서 파일을 찾을 수 없습니다.")
    return FileResponse(path=str(target), filename=safe_name)
