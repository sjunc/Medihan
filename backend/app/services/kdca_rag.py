"""KDCA 건강정보를 기존 LangGraph 근거 목록에 연결하는 비영구 검색 계층.

환자 의료문서 원문을 KDCA로 보내지 않는다. 허용한 콘텐츠 번호만 서버에서 조회한다.
조회 본문은 디스크나 ChromaDB에 저장하지 않으며, 승인된 경우에만 LLM 근거로 사용한다.
"""

from __future__ import annotations

import logging
import os
import re
import time
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

from app.services.government_health_info import CATALOG
from app.services.kdca_api import fetch_kdca_content

LOG = logging.getLogger(__name__)
SOURCE = "질병관리청 국가건강정보포털"


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "true" if default else "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalized(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def _keywords(raw: object) -> list[str]:
    if isinstance(raw, (tuple, list, set)):
        values = [str(value) for value in raw]
    elif isinstance(raw, str):
        values = re.split(r"[,;|\s]+", raw)
    else:
        values = []

    return [
        value
        for value in values
        if len(_normalized(value)) >= 2
    ]


def _content_number(url: str) -> str | None:
    if not url.startswith("https://health.kdca.go.kr/"):
        return None

    for key, values in parse_qs(urlsplit(url).query).items():
        if (
            key.lower() == "cntnts_sn"
            and values
            and values[0].isdigit()
        ):
            return values[0]

    return None


def _score(
    item: dict,
    message: str,
    conditions: str,
    metrics: str,
    glossary: str,
) -> int:
    title = _normalized(item.get("title"))

    if not title:
        return 0

    keywords = {
        _normalized(value)
        for value in _keywords(item.get("keywords"))
    }
    keywords.discard("")

    phrases = {title, *keywords}
    score = 0

    if title in message:
        score += 8

    if title in conditions:
        score += 8

    for phrase in phrases:
        if len(phrase) < 2:
            continue

        if phrase in message:
            score += 3

        if phrase in conditions:
            score += 4

        if phrase in metrics:
            score += 3

        if phrase in glossary:
            score += 2

    return score


@lru_cache(maxsize=64)
def _fetch_cached(content_id: str, bucket: int) -> dict:
    """한 시간 동안만 메모리에 공식 본문을 보유한다."""
    return fetch_kdca_content(content_id)


def _section_excerpt(
    sections: object,
    max_chars: int = 2400,
) -> str:
    if not isinstance(sections, list):
        return ""

    parts: list[str] = []
    remaining = max_chars

    for section in sections[:12]:
        if not isinstance(section, dict):
            continue

        heading = str(
            section.get("title") or "건강정보"
        ).strip()[:80]

        body = str(
            section.get("text") or ""
        ).strip()

        if not body or remaining < 120:
            continue

        piece = (
            f"[{heading}]\n"
            f"{body[:min(1000, remaining - len(heading) - 4)]}"
        )

        parts.append(piece)
        remaining -= len(piece)

    return "\n\n".join(parts)


def retrieve_kdca_sources(
    *,
    message: str = "",
    matched_conditions: list[str] | None = None,
    abnormal_metrics: list[str] | None = None,
    glossary_terms: list[str] | None = None,
    limit: int = 2,
) -> list[dict]:
    """로컬에서 질병명과 검사 항목을 매칭해 공식 출처를 반환한다.

    KDCA로 전달하는 값은 등록된 콘텐츠 번호뿐이다.
    KDCA_AI_CONTEXT_ENABLED=false이면 공식 링크만 제공한다.
    """

    if not _enabled(
        "KDCA_AUTO_SEARCH_ENABLED",
        default=True,
    ):
        return []

    parts = (
        _normalized(message[:500]),
        _normalized(
            " ".join(matched_conditions or [])[:500]
        ),
        _normalized(
            " ".join(abnormal_metrics or [])[:300]
        ),
        _normalized(
            " ".join(glossary_terms or [])[:300]
        ),
    )

    if not any(parts):
        return []

    candidates = []

    for order, entry in enumerate(CATALOG):
        score = _score(entry, *parts)
        url = str(entry.get("url") or "")

        if (
            score > 0
            and url.startswith(
                "https://health.kdca.go.kr/"
            )
        ):
            candidates.append(
                (-score, order, entry)
            )

    candidates.sort(
        key=lambda row: (row[0], row[1])
    )

    allow_body = (
        _enabled("KDCA_AI_CONTEXT_ENABLED")
        and bool(
            os.getenv("KDCA_API_KEY", "").strip()
        )
    )

    results: list[dict] = []

    for _, _, entry in candidates[
        :max(0, min(limit, 3))
    ]:
        url = str(entry["url"])
        content_id = _content_number(url)

        source = {
            "id": f"kdca::{entry['id']}",
            "provider": "kdca",
            "category": "공식건강정보",
            "title": str(entry["title"]),
            "source": SOURCE,
            "url": url,
            "page": 1,
            "content": "",
            "mode": "link_only",
        }

        if allow_body and content_id:
            try:
                response = _fetch_cached(
                    content_id,
                    int(time.time() // 3600),
                )

                if response.get("code") == "S001":
                    body = _section_excerpt(
                        response.get("sections")
                    )

                    if body:
                        source["title"] = (
                            response.get("title")
                            or source["title"]
                        )
                        source["content"] = body
                        source["mode"] = (
                            "official_excerpt"
                        )

            except Exception as exc:
                # KDCA 장애로 의료문서 분석 전체가
                # 중단되지 않도록 공식 링크로 대체한다.
                LOG.warning(
                    "KDCA retrieval failed: %s",
                    type(exc).__name__,
                )

        results.append(source)

    return results