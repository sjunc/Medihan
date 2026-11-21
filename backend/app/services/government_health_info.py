
"""질병관리청 국가건강정보포털 공식 링크 메타데이터 색인.

KDCA view API는 콘텐츠 일련번호 기반 상세 조회 API다.
여기에는 콘텐츠 제목·URL·검색 키워드만 저장하며 본문은 저장하지 않는다.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SOURCE = "질병관리청 국가건강정보포털"
BASE = "https://health.kdca.go.kr/healthinfo/biz/health"
VIEW = f"{BASE}/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do"

EXTRA_CATALOG_CSV = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "kdca_catalog.csv"
)

LOG = logging.getLogger(__name__)

# 기존에 등록된 9개 콘텐츠.
# 기존 콘텐츠 ID와 링크는 변경하지 않는다.
_BASE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "kdca-liver-test",
        "title": "간기능검사",
        "category": "검사정보",
        "keywords": (
            "간기능",
            "간수치",
            "AST",
            "ALT",
            "GGT",
            "감마지티피",
            "R945",
            "간검사",
        ),
        "url": f"{VIEW}?cntnts_sn=5444",
        "updated_at": None,
    },
    {
        "id": "kdca-health-screening",
        "title": "건강검진(국가건강검진)",
        "category": "건강정보",
        "keywords": (
            "건강검진",
            "국가건강검진",
            "검진결과",
            "건강검진결과",
        ),
        "url": f"{VIEW}?cntnts_sn=6671",
        "updated_at": None,
    },
    {
        "id": "kdca-hypertension",
        "title": "고혈압",
        "category": "질환정보",
        "keywords": (
            "고혈압",
            "혈압",
            "수축기혈압",
            "이완기혈압",
        ),
        "url": f"{VIEW}?cntnts_sn=6765",
        "updated_at": "2026-10-21",
    },
    {
        "id": "kdca-diabetes",
        "title": "당뇨병",
        "category": "질환정보",
        "keywords": (
            "당뇨",
            "당뇨병",
            "혈당",
            "공복혈당",
            "당화혈색소",
            "HbA1c",
        ),
        "url": f"{VIEW}?cntnts_sn=5305",
        "updated_at": "2026-10-23",
    },
    {
        "id": "kdca-dyslipidemia",
        "title": "이상지질혈증",
        "category": "질환정보",
        "keywords": (
            "이상지질혈증",
            "고지혈증",
            "콜레스테롤",
            "LDL",
            "HDL",
            "중성지방",
        ),
        "url": f"{VIEW}?cntnts_sn=6715",
        "updated_at": "2026-08-19",
    },
    {
        "id": "kdca-stroke",
        "title": "뇌졸중에 대해서",
        "category": "심뇌혈관질환",
        "keywords": (
            "뇌졸중",
            "뇌경색",
            "뇌출혈",
            "중풍",
        ),
        "url": (
            f"{BASE}/ccvdInfo/ccvcdInfo/"
            "cbvcacdInfoMain.do"
        ),
        "updated_at": None,
    },
    {
        "id": "kdca-heart-attack",
        "title": "심근경색에 대해서",
        "category": "심뇌혈관질환",
        "keywords": (
            "심근경색",
            "급성심근경색",
            "심장마비",
        ),
        "url": (
            f"{BASE}/ccvdInfo/cvcdInfo/"
            "miInfoMain.do"
        ),
        "updated_at": None,
    },
    {
        "id": "kdca-cpr",
        "title": "심폐소생술",
        "category": "응급정보",
        "keywords": (
            "심폐소생술",
            "CPR",
            "심정지",
            "가슴압박",
        ),
        "url": f"{VIEW}?cntnts_sn=6226",
        "updated_at": "2026-05-21",
    },
    {
        "id": "kdca-emergency",
        "title": "응급상황정보",
        "category": "응급정보",
        "keywords": (
            "응급상황",
            "응급처치",
            "응급실",
        ),
        "url": (
            f"{BASE}/gnrlzHealthInfo/healthInfo/"
            "emgncySittnInfoMain.do"
        ),
        "updated_at": None,
    },
)


def _normalize(value: object) -> str:
    """검색용으로 공백·기호·대소문자를 정규화한다."""
    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        str(value or "").lower(),
    )


def _valid_official_url(value: str) -> bool:
    """질병관리청 공식 건강정보 주소인지 확인한다."""
    parsed = urlsplit(value)

    if (
        parsed.scheme != "https"
        or parsed.netloc != "health.kdca.go.kr"
    ):
        return False

    if not parsed.path.startswith(
        "/healthinfo/biz/health/"
    ):
        return False

    return (
        not parsed.username
        and not parsed.password
        and not parsed.fragment
    )


def _catalog_row(
    row: dict[str, str],
) -> dict[str, Any] | None:
    """CSV의 한 행을 검증하고 기존 CATALOG 구조로 변환한다."""
    entry_id = (row.get("id") or "").strip()
    title = (row.get("title") or "").strip()
    content_id = (
        row.get("content_id") or ""
    ).strip()
    category = (
        row.get("category") or "건강정보"
    ).strip()
    updated_at = (
        row.get("updated_at") or ""
    ).strip()

    if not re.fullmatch(
        r"kdca-[a-z0-9-]{2,64}",
        entry_id,
    ):
        return None

    if not (
        1 <= len(title) <= 120
        and 1 <= len(category) <= 50
    ):
        return None

    if not re.fullmatch(
        r"\d{1,10}",
        content_id,
    ):
        return None

    if updated_at and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}",
        updated_at,
    ):
        return None

    url = f"{VIEW}?cntnts_sn={content_id}"

    keywords = tuple(
        keyword.strip()[:60]
        for keyword in (
            row.get("keywords") or ""
        ).split("|")
        if keyword.strip()
    )[:20]

    return {
        "id": entry_id,
        "title": title,
        "category": category,
        "keywords": keywords,
        "url": url,
        "updated_at": updated_at or None,
    }


def _load_catalog() -> tuple[dict[str, Any], ...]:
    """기본 콘텐츠와 CSV의 확장 콘텐츠를 병합한다."""
    entries = list(_BASE_CATALOG)

    seen_ids = {
        item["id"]
        for item in entries
    }

    seen_urls = {
        item["url"]
        for item in entries
    }

    # CSV가 없어도 기존 9개 콘텐츠는 계속 작동한다.
    if not EXTRA_CATALOG_CSV.is_file():
        return tuple(entries)

    try:
        with EXTRA_CATALOG_CSV.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as stream:
            reader = csv.DictReader(stream)

            required = {
                "id",
                "title",
                "category",
                "keywords",
                "content_id",
                "updated_at",
            }

            if not required.issubset(
                reader.fieldnames or []
            ):
                LOG.warning(
                    "KDCA 카탈로그 CSV의 열 이름이 "
                    "올바르지 않습니다."
                )
                return tuple(entries)

            for line_number, row in enumerate(
                reader,
                start=2,
            ):
                # 지나치게 큰 입력 파일 방어.
                if line_number > 5001:
                    break

                item = _catalog_row(row)

                if item is None:
                    LOG.warning(
                        "KDCA 카탈로그 CSV %s행을 "
                        "건너뜁니다.",
                        line_number,
                    )
                    continue

                # 중복 콘텐츠 방지.
                if (
                    item["id"] in seen_ids
                    or item["url"] in seen_urls
                ):
                    continue

                if not _valid_official_url(
                    item["url"]
                ):
                    continue

                entries.append(item)
                seen_ids.add(item["id"])
                seen_urls.add(item["url"])

    except (
        OSError,
        UnicodeError,
        csv.Error,
    ):
        LOG.exception(
            "KDCA 카탈로그 확장 파일을 "
            "읽지 못했습니다."
        )

    return tuple(entries)


# 서버 시작 시 확장 파일을 읽는다.
# CSV 수정 후에는 백엔드를 재시작해야 한다.
CATALOG = _load_catalog()


def search_official_health_info(
    query: str = "",
    limit: int = 6,
) -> dict[str, Any]:
    """입력한 질문과 관련된 KDCA 공식 콘텐츠를 검색한다.

    환자정보나 검색어를 외부 API로 전송하지 않는다.
    일치하는 제목과 링크만 반환한다.
    """
    cleaned = re.sub(
        r"\s+",
        " ",
        str(query or ""),
    ).strip()[:100]

    normalized = _normalize(cleaned)

    tokens = [
        _normalize(token)
        for token in re.findall(
            r"[0-9A-Za-z가-힣]+",
            cleaned,
        )
        if len(_normalize(token)) >= 2
    ]

    limit = max(
        0,
        min(int(limit), 20),
    )

    ranked: list[
        tuple[int, int, dict[str, Any]]
    ] = []

    for index, item in enumerate(CATALOG):
        title = _normalize(
            item["title"]
        )

        keywords = {
            _normalize(keyword)
            for keyword in item["keywords"]
            if len(_normalize(keyword)) >= 2
        }

        score = 0

        if normalized:
            # 제목이 정확히 일치하면 가장 높은 점수.
            if title == normalized:
                score += 20

            elif (
                len(title) >= 2
                and title in normalized
            ):
                score += 10

            # 사전 등록한 검사명·질병명 별칭.
            score += sum(
                5
                for keyword in keywords
                if keyword in normalized
            )

            score += sum(
                2
                for token in tokens
                if (
                    token == title
                    or token in keywords
                )
            )

            if score == 0:
                continue

        ranked.append(
            (-score, index, item)
        )

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    items = [
        {
            "id": entry["id"],
            "title": entry["title"],
            "category": entry["category"],
            "url": entry["url"],
            "updated_at": entry["updated_at"],
            "source": SOURCE,
        }
        for _, _, entry in ranked[:limit]
    ]

    return {
        "query": cleaned,
        "source": SOURCE,
        "mode": "official_links_only",
        "total_catalog_items": len(CATALOG),
        "items": items,
        "notice": (
            "공식 콘텐츠의 제목과 링크만 제공합니다. "
            "의료적 판단은 담당 의료진과 상담하세요."
        ),
    }
