"""LangChain @tool 기반 도구 모음: 수치 판정, 질병코드·용어 조회, 의학 근거 RAG, 정책·병원 웹 검색, 보고서 생성."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from langchain_core.tools import tool

from app.services.document_facts import compute_document_facts
from app.services.glossary_lookup import lookup_glossary
from app.services.health_criteria import evaluate_metrics
from app.services.kcd_lookup import lookup_kcd_codes
from app.services.rag_service import RAG_SERVICE
from app.services.report_exporter import generate_reports_bundle


def _run_web_search(query: str, max_results: int = 4) -> List[Dict[str, str]]:
    """DuckDuckGo를 통해 실시간 인터넷 검색을 수행하고 실패 시 빈 리스트를 반환한다."""
    try:
        from duckduckgo_search import DDGS

        results: List[Dict[str, str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="kr-kr", safesearch="moderate", max_results=max_results):
                results.append(
                    {
                        "title": str(r.get("title", "")),
                        "snippet": str(r.get("body", "")),
                        "url": str(r.get("href", "")),
                    }
                )
        return results
    except Exception:
        return []


@tool
def analyze_health_metrics_tool(metrics_json: str, gender: str = "unknown") -> str:
    """건강검진 수치 JSON을 국민건강보험공단 기준에 따라 정량 판정(정상A/정상B/질환의심)합니다."""
    metrics = json.loads(metrics_json) if metrics_json else {}
    return json.dumps(evaluate_metrics(metrics, gender=gender), ensure_ascii=False)


@tool
def search_medical_guideline_tool(query: str, categories_csv: str = "의학기준,질병정보,의학용어,문서안내") -> str:
    """knowledge_base 문서 기반 ChromaDB 벡터 검색으로 판정기준·질병정보·용어·서류 읽는 법을 조회합니다."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    categories = [c.strip() for c in categories_csv.split(",") if c.strip()]
    docs = RAG_SERVICE.search(query=query, category=categories or None, top_k=4, api_key=api_key)
    return json.dumps(docs, ensure_ascii=False)


@tool
def lookup_kcd_code_tool(document_text: str) -> str:
    """의료 서류 텍스트에서 질병코드(KCD-9)를 찾아 공식 병명(한글·영문)을 정확 일치로 조회합니다."""
    return json.dumps(lookup_kcd_codes(document_text), ensure_ascii=False)


@tool
def lookup_glossary_tool(document_text: str) -> str:
    """서류에 등장한 병명·시술·검사 용어를 지식베이스 용어 사전에서 정확 조회해 쉬운 말과 설명을 돌려줍니다."""
    return json.dumps(lookup_glossary(document_text), ensure_ascii=False)


@tool
def compute_document_facts_tool(document_text: str) -> str:
    """서류의 입·퇴원일 등 날짜 기반 사실(입원 기간)을 코드로 정확히 계산합니다."""
    return json.dumps(compute_document_facts(document_text), ensure_ascii=False)


@tool
def search_public_health_policy_tool(query: str) -> str:
    """국가건강검진 제도, 확진검사 비용 지원 등 정부·검진 지원 제도를 문서 검색 및 인터넷 검색으로 조회합니다."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    rag_policies = RAG_SERVICE.search(query=query, category="정부정책", top_k=2, api_key=api_key)
    web_hits = _run_web_search(f"국민건강보험공단 국가건강검진 {query} 지원 정책", max_results=3)
    return json.dumps({"rag_policies": rag_policies, "web_results": web_hits}, ensure_ascii=False)


@tool
def recommend_specialist_hospitals_tool(departments_csv: str, location: str) -> str:
    """진료과와 지역으로 병원을 웹 검색합니다. 검색 결과만 돌려주며 임의의 병원 정보를 만들지 않습니다."""
    depts = [d.strip() for d in departments_csv.split(",") if d.strip()]
    location = (location or "").strip()
    if not depts or not location:
        missing = "진료 지역을 입력한 뒤 검색해 주세요." if depts else "서류에서 권장 진료과를 확인하지 못했습니다. 담당 의사에게 진료과를 문의해 주세요."
        return json.dumps(
            {"location": location, "recommended_departments": depts, "hospitals": [], "notice": missing},
            ensure_ascii=False,
        )

    hospitals: List[Dict[str, str]] = []
    seen_urls = set()
    for dept in depts[:2]:
        for hit in _run_web_search(f"{location} {dept} 병원", max_results=4):
            url = hit.get("url", "")
            if not hit.get("title") or url in seen_urls:
                continue
            seen_urls.add(url)
            hospitals.append(
                {
                    "name": hit["title"][:60],
                    "department": dept,
                    "address": location,
                    "reason": hit.get("snippet", "")[:140],
                    "url": url,
                }
            )
    notice = "" if hospitals else "검색 결과를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."
    return json.dumps(
        {"location": location, "recommended_departments": depts, "hospitals": hospitals[:6], "notice": notice},
        ensure_ascii=False,
    )


@tool
def generate_multi_format_report_tool(report_payload_json: str) -> str:
    """분석 결과, 참고 의학 기준, 대화 요약을 Word(.docx), PDF(.pdf), 이미지(.png) 보고서로 저장합니다."""
    payload = json.loads(report_payload_json)
    files = generate_reports_bundle(payload, formats=["docx", "pdf", "png"])
    return json.dumps(files, ensure_ascii=False)
