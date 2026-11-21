"""LangGraph 기반 Medihan 의학근거 우선(Evidence-First) -> 맞춤형 요약/대화 -> 프리미엄 확장 워크플로우."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app.agent.tools import (
    analyze_health_metrics_tool,
    compute_document_facts_tool,
    generate_multi_format_report_tool,
    lookup_glossary_tool,
    lookup_kcd_code_tool,
    recommend_specialist_hospitals_tool,
    search_medical_guideline_tool,
    search_public_health_policy_tool,
)
from app.config import openai_model
from app.services.ocr_masking import extract_health_metrics
from app.services.kdca_rag import retrieve_kdca_sources

INTENTS = ("analyze", "summarize", "policy_search", "hospital_recommend", "export_report", "chat")


class MedihanState(TypedDict, total=False):
    user_message: str
    action_type: str  # auto | analyze | policy_search | summarize | hospital_recommend | export_report
    location: str
    gender: str
    metrics: Dict[str, Any]
    safe_text: str
    chat_history: List[Dict[str, str]]
    api_key: Optional[str]

    # 그래프 실행 중간/출력 상태
    intent: str
    needs_policy_search: bool
    needs_hospital: bool
    needs_report: bool
    executed_nodes: List[str]
    evaluations: List[Dict[str, Any]]
    recommended_departments: List[str]
    confirm_exam_eligible: List[str]
    rag_sources: List[Dict[str, Any]]
    kcd_codes: List[Dict[str, Any]]
    unmatched_codes: List[str]
    glossary_hits: List[Dict[str, Any]]
    document_facts: Dict[str, str]
    hospital_notice: str
    policy_results: Dict[str, Any]
    assistant_reply: str
    llm_mode: str
    llm_error: str
    hospitals: List[Dict[str, Any]]
    web_hospitals: List[Dict[str, Any]]
    report_files: Dict[str, Dict[str, str]]
    open_right_panel: bool
    right_panel_tab: str


_FALLBACK_KEYWORDS = {
    "policy_search": ("정책", "지원", "무료", "확진검사", "정부", "혜택", "국가검진", "면제", "제도"),
    "hospital_recommend": ("병원", "의원", "어디로 가", "진료과", "가까운"),
    "export_report": ("보고서", "리포트", "워드", "docx", "pdf", "이미지 저장", "다운로드", "저장해"),
    "summarize": ("요약", "3줄", "간단히", "정리"),
}


def _classify_intent(msg: str, api_key: str) -> Optional[str]:
    """질문 의도를 LLM으로 분류한다. 키가 없거나 실패하면 None을 돌려 키워드 규칙으로 넘어간다."""
    if not api_key or not msg:
        return None
    try:
        llm = ChatOpenAI(model=openai_model(), api_key=api_key, temperature=0)
        res = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "의료 서류 해설 서비스의 사용자 요청을 다음 중 정확히 하나로 분류해 그 단어만 출력하세요.\n"
                        "analyze: 서류 전체 설명 요청 / summarize: 요약 요청 / policy_search: 검진·지원 제도 문의 / "
                        "hospital_recommend: 병원·진료과 추천 / export_report: 보고서 파일 저장 / chat: 그 밖의 질문"
                    )
                ),
                HumanMessage(content=msg),
            ]
        )
        label = str(res.content).strip().lower()
        return label if label in INTENTS else None
    except Exception:
        return None


def _keyword_intents(msg: str) -> Dict[str, bool]:
    low = msg.lower()
    return {name: any(k in low for k in words) for name, words in _FALLBACK_KEYWORDS.items()}


def router_node(state: MedihanState) -> Dict[str, Any]:
    """요청 유형(버튼 action_type 우선, 자유 질문은 LLM 분류, 키 없으면 키워드)에 따라 실행 경로를 결정한다."""
    msg = (state.get("user_message") or "").strip()
    action = state.get("action_type") or "auto"
    api_key = (state.get("api_key") or os.getenv("OPENAI_API_KEY") or "").strip()

    existing_metrics = dict(state.get("metrics") or {})
    typed_metrics = extract_health_metrics(msg)
    if typed_metrics:
        existing_metrics.update(typed_metrics)

    if action in INTENTS:
        intent = action
    elif action == "auto" and not msg and (existing_metrics or state.get("safe_text")):
        intent = "analyze"
    else:
        intent = _classify_intent(msg, api_key)
        if intent is None:
            flags = _keyword_intents(msg)
            intent = next((name for name in ("export_report", "hospital_recommend", "policy_search", "summarize") if flags[name]), "chat")

    needs_policy = intent == "policy_search"
    needs_hospital = intent == "hospital_recommend"
    needs_report = intent == "export_report"

    nodes = list(state.get("executed_nodes") or [])
    nodes.append("router_node")

    return {
        "metrics": existing_metrics,
        "intent": intent,
        "needs_policy_search": needs_policy,
        "needs_hospital": needs_hospital,
        "needs_report": needs_report,
        "executed_nodes": nodes,
        "open_right_panel": needs_hospital or needs_report,
        "right_panel_tab": "hospitals" if needs_hospital else "reports",
    }


def metric_eval_node(state: MedihanState) -> Dict[str, Any]:
    """건강검진 수치를 국민건강보험공단 기준에 따라 정량 판정한다."""
    metrics = state.get("metrics") or {}
    gender = state.get("gender") or "unknown"
    raw = analyze_health_metrics_tool.invoke({"metrics_json": json.dumps(metrics, ensure_ascii=False), "gender": gender})
    parsed = json.loads(raw)

    nodes = list(state.get("executed_nodes") or [])
    nodes.append("metric_eval_node")

    return {
        "evaluations": parsed.get("evaluations", []),
        "recommended_departments": parsed.get("recommended_departments", []),
        "confirm_exam_eligible": parsed.get("confirm_exam_eligible", []),
        "executed_nodes": nodes,
    }


def _split_departments(text: str) -> List[str]:
    """'외과(소화기·일반외과), 응급의학과' 같은 진료과 문자열을 괄호 밖 쉼표 기준으로 나눈다."""
    return [d.strip() for d in re.split(r",\s*(?![^()]*\))", text) if d.strip()]


def rag_evidence_node(state: MedihanState) -> Dict[str, Any]:
    """서류의 질병코드·용어를 사전에서 정확 조회하고, 서류 종류 안내·판정기준·가이드는 벡터 검색으로 보완한다."""
    msg = state.get("user_message") or ""
    safe_text = state.get("safe_text") or ""
    evaluations = state.get("evaluations") or []
    abnormal_items = [str(e.get("item", "")) for e in evaluations if e.get("severity") != "normal"]
    all_items = [str(e.get("item", "")) for e in evaluations]

    lookup: Dict[str, Any] = {"codes": [], "unmatched_codes": []}
    glossary: List[Dict[str, Any]] = []
    facts: Dict[str, str] = {}
    if safe_text:
        lookup = json.loads(lookup_kcd_code_tool.invoke({"document_text": safe_text}))
        glossary = json.loads(lookup_glossary_tool.invoke({"document_text": safe_text}))
        facts = json.loads(compute_document_facts_tool.invoke({"document_text": safe_text}))

    kcd_sources = [
        {
            "id": f"kcd9::{c['code']}",
            "category": "질병정보",
            "title": f"{c['code']} {c['name']}",
            "source": "KCD-9 상병마스터",
            "page": 1,
            "content": " / ".join([c["name"], *c.get("aliases", []), c.get("en", "")]).strip(" /"),
            "match": "질병코드 일치",
        }
        for c in lookup["codes"]
    ]

    doc_snippet = safe_text.replace("[개인정보_마스킹됨]", " ")[:400]
    query_parts = [msg, doc_snippet, *(g["term"] for g in glossary)]
    query_parts.extend(abnormal_items or all_items[:4])
    query = " ".join(p for p in query_parts if p).strip()

    searched: List[Dict[str, Any]] = []
    if query:
        searched = json.loads(search_medical_guideline_tool.invoke({"query": query}))
    if doc_snippet.strip():
        guide = json.loads(
            search_medical_guideline_tool.invoke({"query": doc_snippet, "categories_csv": "문서안내"})
        )
        known = {d.get("id") for d in searched}
        searched = [d for d in guide if d.get("id") not in known][:1] + searched

    departments = list(state.get("recommended_departments") or [])
    for g in glossary:
        for dept in _split_departments(g.get("details", {}).get("진료과", "")):
            if dept not in departments:
                departments.append(dept)

    nodes = list(state.get("executed_nodes") or [])
    nodes.append("rag_evidence_node")

    return {
        "rag_sources": (
            retrieve_kdca_sources(
                message=msg,
                matched_conditions=[
                    str(c.get("name", ""))
                    for c in lookup["codes"]
                ],
                abnormal_metrics=abnormal_items,
                glossary_terms=[
                    str(g.get("term", ""))
                    for g in glossary
                ],
                limit=2,
            )
            + kcd_sources
            + searched
        )[:12],
        "kcd_codes": lookup["codes"],
        "unmatched_codes": lookup["unmatched_codes"],
        "glossary_hits": glossary,
        "document_facts": facts,
        "recommended_departments": departments,
        "executed_nodes": nodes,
    }


def policy_search_node(state: MedihanState) -> Dict[str, Any]:
    """국가건강검진 제도 및 정부 지원 사업을 조회한다. 질의는 사용자 질문과 판정 결과에서 만든다."""
    msg = (state.get("user_message") or "").strip()
    eligible = state.get("confirm_exam_eligible") or []
    query = msg or " ".join(eligible)
    if not query:
        query = (state.get("safe_text") or "")[:120]

    policy_data: Dict[str, Any] = {"rag_policies": [], "web_results": []}
    if query:
        policy_data = json.loads(search_public_health_policy_tool.invoke({"query": query}))

    nodes = list(state.get("executed_nodes") or [])
    nodes.append("policy_search_node")

    return {"policy_results": policy_data, "executed_nodes": nodes}


def _excerpt(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _build_fallback_reply(state: MedihanState) -> str:
    """AI를 쓸 수 없을 때, 코드·사전·판정기준·지식베이스에서 실제로 조회된 내용만 그대로 보여 준다(문장을 지어내지 않는다)."""
    intent = state.get("intent") or "chat"
    evaluations = state.get("evaluations") or []
    rag_sources = state.get("rag_sources") or []
    policy_results = state.get("policy_results") or {}
    glossary = state.get("glossary_hits") or []
    kcd_codes = state.get("kcd_codes") or []
    document_text = (state.get("safe_text") or "").strip()
    llm_error = state.get("llm_error") or ""
    lines: List[str] = []

    if intent == "policy_search" and policy_results:
        lines.append("### 🏛️ 국가건강검진 · 정부 지원 제도 안내")
        for pol in policy_results.get("rag_policies", []):
            lines.append(f"**• {pol.get('title')}** *(출처: {pol.get('source')})*")
            lines.append(pol.get("content", ""))
            lines.append("")
        for w in policy_results.get("web_results", [])[:3]:
            lines.append(f"- **{w.get('title')}**: {w.get('snippet')} ({w.get('url')})")
        return "\n".join(lines)

    if document_text:
        lines.append("### ⚠️ AI 해설을 생성하지 못했습니다")
        if llm_error:
            lines.append(f"AI 호출 중 오류가 발생했습니다: `{llm_error}`")
        else:
            lines.append("OpenAI API 키가 설정되지 않아 서류 내용을 AI로 풀어 쓸 수 없습니다. 화면 상단에서 API 키를 입력한 뒤 다시 요청해 주세요.")
        lines.append("\n아래는 서류에서 자동으로 확인된 내용입니다.\n")

        if kcd_codes:
            lines.append("**질병코드 조회 (KCD-9)**")
            for c in kcd_codes:
                lines.append(f"- {c['code']}: {c['name']}" + (f" ({c['en']})" if c.get("en") else ""))
            lines.append("")
        if glossary:
            lines.append("**용어 사전 조회**")
            for g in glossary:
                easy = g["details"].get("쉬운 말", "")
                lines.append(f"- {g['term']}" + (f" → {easy}" if easy else ""))
            lines.append("")
        if evaluations:
            lines.append("**검진 수치 판정 (국민건강보험공단 판정기준)**")
            for ev in evaluations:
                lines.append(f"- {ev['item']}: {ev['value']} {ev['unit']} → {ev['status']} (기준: {ev['reference']})")
            lines.append("")
        lines.append("**인식된 서류 원문 (개인정보 가림)**")
        lines.append("```\n" + document_text[:3000] + "\n```")
        return "\n".join(lines)

    lines.append("### 🩺 답변을 준비하지 못했습니다")
    lines.append(
        f"AI 호출 중 오류가 발생했습니다: `{llm_error}`" if llm_error else "OpenAI API 키가 없어 자유 질문에는 답할 수 없습니다. 화면 상단에서 API 키를 입력해 주세요."
    )
    if evaluations:
        lines.append("\n**입력하신 수치의 판정 결과**")
        for ev in evaluations:
            lines.append(f"- {ev['item']}: {ev['value']} {ev['unit']} → {ev['status']} (기준: {ev['reference']})")
    if rag_sources:
        lines.append("\n**관련 지식베이스 자료**")
        for src in rag_sources[:3]:
            lines.append(f"- **{src.get('title')}** *({src.get('source')})*: {_excerpt(src.get('content', ''))}")
    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "당신은 진단서·소견서·입퇴원확인서·건강검진 결과통보서·처방전 등 의료문서를 의학 지식이 없는 일반인이 이해하도록 풀어 설명하는 AI 상담사 '메디한(Medihan)'입니다.\n"
    "공통 원칙:\n"
    "1. 설명 대상은 [document_text]입니다. 먼저 서류 종류를 파악하고, [document_guides]가 있으면 그 서류의 읽는 법을 참고하세요. OCR 텍스트라 오타가 있을 수 있으니 앞뒤 문맥으로 바로잡아 읽되, 서류에 적히지 않은 사실(병명·시술·날짜·수치·진행 정도·예후)은 절대 만들지 말고 서류의 표현보다 강하거나 약하게 바꾸지 마세요.\n"
    "2. '[개인정보_마스킹됨]'은 가려진 개인정보입니다. 추측하거나 언급하지 마세요.\n"
    "3. 모든 의학 용어는 중학생도 아는 일상어로 풀어 쓰되, 서류에 적힌 용어 자체는 '서류 표기'로 함께 보여 주세요. 쉬운 말은 [glossary]·[kcd_codes]에 있으면 그 내용을 우선 근거로 쓰고, 없으면 서류의 앞뒤 문맥과 일반 의학 지식으로 풀어 쓰되 뜻이 불확실하면 단정하지 말고 담당 의사에게 확인하라고 안내하세요. 병명은 어느 장기·부위의 병인지도 함께 알려 주세요.\n"
    "4. 질병코드의 공식 병명은 [kcd_codes]에 있는 값만 근거로 쓰세요. 서류의 병명과 공식 병명이 다르면 그 차이를 알려 주세요. [unmatched_codes]는 OCR 오인식일 수 있으므로 서류의 병명·질병분류기호 칸에 실제로 적힌 코드일 때만 '질병코드표에서 확인되지 않아 담당 의사에게 확인이 필요하다'고 알리세요.\n"
    "5. 날짜는 서류에 적힌 그대로 쓰고, 입원 기간은 [computed_facts]의 값을 그대로 쓰세요. 직접 계산하지 마세요.\n"
    "6. 서류에 적힌 판정(정상A·정상B·질환의심 등)과 수치가 있으면 그대로 따르고, [evaluations]는 같은 수치를 국민건강보험공단 기준으로 다시 판정한 값입니다. 둘이 다르면 차이를 알려 주세요. 서류에 수치가 없으면 정상 여부를 판단하지 마세요.\n"
    "7. 서류에 없는 항목은 아예 언급하지 마세요. '해당 없음', '기재되지 않음', '확인되지 않음' 같은 빈칸 채우기 문장을 쓰지 마세요.\n"
    "8. 검진 기준·제도·생활관리 설명이 필요할 때는 [medical_references]에 있는 내용만 근거로 쓰고 제목을 인용하세요. 거기에 없는 제도·금액·기관은 말하지 마세요.\n"
)

_ANALYSIS_FORMAT = (
    "출력 형식(서류 설명 요청):\n"
    "### 📝 한눈에 보기\n"
    "- 이 서류가 무슨 서류이고 무엇을 말하는지 3~5문장으로 쉽게 요약하세요. 서류에 실제로 있는 내용으로만 구성하고, 이 문단에는 서류의 전문 용어를 그대로 쓰지 말고 모두 쉬운 말로 바꿔 쓰세요.\n"
    "### 🔍 항목별 해설\n"
    "- 서류에 실제로 적힌 항목만, 서류에 나온 순서와 항목명 그대로 '서류 표기 → 쉬운 말과 짧은 설명' 형태로 쓰세요. 서류 종류에 맞는 구조(진단서는 병명·치료·소견, 검진 통보서는 검사 항목별 수치와 판정, 처방전은 약과 용법 등)를 따르세요.\n"
    "마지막 줄에 '원본 서류와 담당 의사의 설명이 우선이며 이 설명은 이해를 돕기 위한 참고용입니다.'를 쓰세요.\n"
)

_CHAT_FORMAT = (
    "출력 형식: 사용자의 질문에 먼저 직접 답하고, 필요할 때만 서류 내용을 근거로 짧게 덧붙이세요. 이전 대화와 이어지는 질문이면 같은 설명을 반복하지 마세요. 서류에 근거가 없는 내용은 모른다고 말하고, 의학적 판단이 필요한 내용은 담당 의사 상담을 권하세요.\n"
)

_SUMMARY_FORMAT = (
    "출력 형식: 서류(또는 입력된 수치)의 핵심만 3줄 이내로 요약하세요. 서류에 없는 내용은 쓰지 마세요.\n"
)


def _build_context_block(state: MedihanState) -> Dict[str, Any]:
    rag_sources = state.get("rag_sources") or []
    policy_results = state.get("policy_results") or {}
    return {
        "document_text": (state.get("safe_text") or "")[:6000] or None,
        "computed_facts": state.get("document_facts") or {},
        "kcd_codes": [
            {"code": c["code"], "name": c["name"], "aliases": c.get("aliases", []), "en": c.get("en", "")}
            for c in state.get("kcd_codes", [])
        ],
        "unmatched_codes": state.get("unmatched_codes", []),
        "glossary": [
            {"term": g["term"], "matched_by": g["matched_by"], **g["details"]} for g in state.get("glossary_hits", [])
        ],
        "evaluations": state.get("evaluations") or [],
        "confirm_exam_eligible": state.get("confirm_exam_eligible", []),
        "document_guides": [
            {"title": d.get("title"), "content": d.get("content")} for d in rag_sources if d.get("category") == "문서안내"
        ],
        "medical_references": [
            {
                "title": d.get("title"),
                "source": d.get("source"),
                "content": d.get("content"),
                "url": d.get("url", ""),
            }
            for d in rag_sources
            if (
                d.get("source") != "KCD-9 상병마스터"
                and d.get("category") != "문서안내"
                and str(d.get("content") or "").strip()
            )
        ],
        "official_links": [
            {
                "title": d.get("title"),
                "source": d.get("source"),
                "url": d.get("url"),
            }
            for d in rag_sources
            if (
                d.get("provider") == "kdca"
                and d.get("url")
            )
        ],
        "policy_references": policy_results or None,
        "panel_action": "추천 병원 목록 준비 완료" if state.get("needs_hospital") else ("보고서 파일 생성 완료" if state.get("needs_report") else None),
    }


def chat_summary_node(state: MedihanState) -> Dict[str, Any]:
    """서류 원문과 도구 조회 결과(코드·용어·판정·RAG 근거)를 LLM에 주어 서류에 맞는 해설을 생성한다."""
    api_key = (state.get("api_key") or os.getenv("OPENAI_API_KEY") or "").strip()
    user_msg = (state.get("user_message") or "").strip() or "업로드한 의료 서류를 알기 쉽게 설명해줘."
    intent = state.get("intent") or "chat"

    nodes = list(state.get("executed_nodes") or [])
    nodes.append("chat_summary_node")

    if not api_key:
        return {"assistant_reply": _build_fallback_reply(state), "llm_mode": "standard_rule", "executed_nodes": nodes}

    system_prompt = _SYSTEM_PROMPT + {"analyze": _ANALYSIS_FORMAT, "summarize": _SUMMARY_FORMAT}.get(intent, _CHAT_FORMAT)

    messages: List[Any] = [SystemMessage(content=system_prompt)]
    for turn in (state.get("chat_history") or [])[-6:]:
        role, content = turn.get("role"), turn.get("content", "")
        if role == "user" and content:
            messages.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            messages.append(AIMessage(content=content))

    messages.append(
        HumanMessage(
            content=(
                f"[사용자 질문]\n{user_msg}\n\n"
                f"[서류 원문 · 도구 조회 결과 · 의학 참고 자료]\n{json.dumps(_build_context_block(state), ensure_ascii=False)}"
            )
        )
    )

    llm_error = ""
    try:
        llm = ChatOpenAI(model=openai_model(), api_key=api_key, temperature=0.2)
        reply = str(llm.invoke(messages).content).strip()
        llm_mode = "openai"
    except Exception as exc:
        llm_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        reply = _build_fallback_reply({**state, "llm_error": llm_error})
        llm_mode = "standard_rule"

    return {"assistant_reply": reply, "llm_mode": llm_mode, "llm_error": llm_error, "executed_nodes": nodes}


def premium_hospital_node(state: MedihanState) -> Dict[str, Any]:
    """서류·판정에서 도출된 진료과와 사용자가 지정한 지역으로 병원을 검색한다."""
    depts = state.get("recommended_departments") or []
    location = (state.get("location") or "").strip()
    raw = recommend_specialist_hospitals_tool.invoke({"departments_csv": ",".join(depts), "location": location})
    parsed = json.loads(raw)

    nodes = list(state.get("executed_nodes") or [])
    nodes.append("premium_hospital_node")

    return {
        "hospitals": parsed.get("hospitals", []),
        "hospital_notice": parsed.get("notice", ""),
        "open_right_panel": True,
        "right_panel_tab": "hospitals",
        "executed_nodes": nodes,
    }


def premium_report_node(state: MedihanState) -> Dict[str, Any]:
    """Word(.docx), PDF(.pdf), Image(.png) 다중 포맷 보고서를 생성한다."""
    payload = {
        "evaluations": state.get("evaluations", []),
        "summary_text": state.get("assistant_reply", ""),
        "rag_sources": state.get("rag_sources", []),
        "hospitals": state.get("hospitals", []),
    }
    raw = generate_multi_format_report_tool.invoke({"report_payload_json": json.dumps(payload, ensure_ascii=False)})
    files = json.loads(raw)

    nodes = list(state.get("executed_nodes") or [])
    nodes.append("premium_report_node")

    return {
        "report_files": files,
        "open_right_panel": True,
        "right_panel_tab": "reports",
        "executed_nodes": nodes,
    }


def _route_after_rag(state: MedihanState) -> str:
    # 서류에서 확진검사 대상이 판정되면 분석 단계에서 지원 제도도 함께 조회한다
    if state.get("needs_policy_search") or (state.get("intent") == "analyze" and state.get("confirm_exam_eligible")):
        return "policy_search_node"
    return "chat_summary_node"


def _route_after_chat(state: MedihanState) -> str:
    if state.get("needs_report"):
        return "premium_report_node"
    if state.get("needs_hospital"):
        return "premium_hospital_node"
    return END


def build_medihan_graph():
    """Medihan LangGraph StateGraph를 컴파일하여 반환한다."""
    graph = StateGraph(MedihanState)
    graph.add_node("router_node", router_node)
    graph.add_node("metric_eval_node", metric_eval_node)
    graph.add_node("rag_evidence_node", rag_evidence_node)
    graph.add_node("policy_search_node", policy_search_node)
    graph.add_node("chat_summary_node", chat_summary_node)
    graph.add_node("premium_hospital_node", premium_hospital_node)
    graph.add_node("premium_report_node", premium_report_node)

    graph.set_entry_point("router_node")
    graph.add_edge("router_node", "metric_eval_node")
    graph.add_edge("metric_eval_node", "rag_evidence_node")
    graph.add_conditional_edges(
        "rag_evidence_node",
        _route_after_rag,
        {
            "policy_search_node": "policy_search_node",
            "chat_summary_node": "chat_summary_node",
        },
    )
    graph.add_edge("policy_search_node", "chat_summary_node")
    graph.add_conditional_edges(
        "chat_summary_node",
        _route_after_chat,
        {
            "premium_hospital_node": "premium_hospital_node",
            "premium_report_node": "premium_report_node",
            END: END,
        },
    )
    graph.add_edge("premium_hospital_node", END)
    graph.add_edge("premium_report_node", END)

    return graph.compile()


MEDIHAN_GRAPH = build_medihan_graph()
