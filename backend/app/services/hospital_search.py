"""카카오 로컬 API 기반 병원 장소 검색.

실제 장소 검색은 병원 카테고리 HP8로 제한한다.
의료문서 원문과 환자정보를 카카오 서버에 전송하지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

KAKAO_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/keyword.json"
)
MAX_RESPONSE_BYTES = 512 * 1024


class HospitalSearchError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


def _department(value: str) -> str:
    """진료과 표기의 설명 괄호를 제외해 검색어로 변환한다."""
    clean = re.sub(
        r"\([^)]*\)",
        "",
        str(value or ""),
    )
    clean = re.sub(
        r"[^0-9A-Za-z가-힣\s]",
        " ",
        clean,
    )
    return " ".join(clean.split())[:40]


def _search_kakao(
    query: str,
    key: str,
    *,
    latitude: float | None,
    longitude: float | None,
    radius: int,
) -> list[dict]:
    params: dict[str, str | int] = {
        "query": query,
        "category_group_code": "HP8",
        "size": 15,
        "page": 1,
    }

    if latitude is not None and longitude is not None:
        params.update({
            "x": f"{longitude:.6f}",
            "y": f"{latitude:.6f}",
            "radius": radius,
            "sort": "distance",
        })

    request = Request(
        f"{KAKAO_SEARCH_URL}?{urlencode(params)}",
        headers={
            "Authorization": f"KakaoAK {key}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(
                MAX_RESPONSE_BYTES + 1
            )

    except HTTPError as exc:
        if exc.code in (401, 403):
            raise HospitalSearchError(
                "카카오 REST API 키 또는 "
                "로컬 API 권한을 확인하세요.",
                503,
            ) from None

        if exc.code == 429:
            raise HospitalSearchError(
                "카카오 장소 검색 요청 한도에 도달했습니다. "
                "잠시 후 다시 검색하세요.",
                503,
            ) from None

        raise HospitalSearchError(
            f"카카오 장소 검색 HTTP {exc.code} 오류"
        ) from None

    except (URLError, TimeoutError, OSError):
        raise HospitalSearchError(
            "카카오 장소 검색 서버에 연결하지 못했습니다."
        ) from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise HospitalSearchError(
            "장소 검색 응답 크기가 허용 범위를 "
            "초과했습니다."
        )

    try:
        result = json.loads(raw)
        documents = result["documents"]

        if not isinstance(documents, list):
            raise TypeError(
                "documents must be list"
            )

        return documents

    except (ValueError, KeyError, TypeError):
        raise HospitalSearchError(
            "카카오 장소 검색 응답 형식이 "
            "올바르지 않습니다."
        ) from None


def search_hospitals(
    *,
    departments: list[str],
    location: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    radius: int = 5000,
    limit: int = 10,
) -> dict:
    """위치 좌표 또는 지역명으로 실제 병원 장소를 검색한다.

    좌표 검색: 반경 제한 및 직선거리순 정렬.
    지역 검색: 장소 키워드 검색으로, 거리순은 아님.
    """

    depts = list(
        dict.fromkeys(
            filter(
                None,
                (
                    _department(dept)
                    for dept in (departments or [])
                ),
            )
        )
    )[:2]

    region = " ".join(
        str(location or "").split()
    )[:70]

    has_lat = latitude is not None
    has_lon = longitude is not None

    if has_lat != has_lon:
        raise HospitalSearchError(
            "위도와 경도를 함께 입력해야 합니다.",
            400,
        )

    nearby = has_lat and has_lon

    if nearby:
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise HospitalSearchError(
                "위도 또는 경도 값이 올바르지 않습니다.",
                400,
            )

    safe_radius = max(
        500,
        min(int(radius), 20000),
    )

    max_results = max(
        1,
        min(int(limit), 15),
    )

    response = {
        "location": (
            "현재 위치 기준"
            if nearby
            else region
        ),
        "recommended_departments": depts,
        "mode": (
            "nearby"
            if nearby
            else "region"
        ),
        "provider": "kakao_local",
        "radius_m": (
            safe_radius
            if nearby
            else None
        ),
        "hospitals": [],
        "notice": "",
    }

    if not depts:
        response["notice"] = (
            "진료과를 선택하거나 직접 입력해 주세요."
        )
        return response

    if not nearby and not region:
        response["notice"] = (
            "현재 위치를 허용하거나 "
            "검색할 지역을 입력해 주세요."
        )
        return response

    api_key = os.getenv(
        "KAKAO_REST_API_KEY",
        "",
    ).strip()

    if not api_key:
        raise HospitalSearchError(
            "KAKAO_REST_API_KEY가 설정되지 않았습니다.",
            503,
        )

    places: dict[str, dict] = {}

    for dept in depts:
        query = (
            dept
            if nearby
            else f"{region} {dept}"
        )

        for doc in _search_kakao(
            query,
            api_key,
            latitude=latitude,
            longitude=longitude,
            radius=safe_radius,
        ):
            if (
                not isinstance(doc, dict)
                or doc.get("category_group_code") != "HP8"
            ):
                continue

            place_id = str(
                doc.get("id") or ""
            )

            name = str(
                doc.get("place_name") or ""
            ).strip()

            if (
                not place_id.isdigit()
                or not name
                or place_id in places
            ):
                continue

            raw_distance = str(
                doc.get("distance") or ""
            )

            distance_m = (
                int(raw_distance)
                if nearby and raw_distance.isdigit()
                else None
            )

            places[place_id] = {
                "id": f"kakao::{place_id}",
                "name": name,
                "department": dept,
                "address": str(
                    doc.get("road_address_name")
                    or doc.get("address_name")
                    or ""
                ),
                "phone": str(
                    doc.get("phone") or ""
                ),
                "distance_m": distance_m,
                "category": str(
                    doc.get("category_name") or ""
                ),
                "url": (
                    "https://place.map.kakao.com/"
                    f"{place_id}"
                ),
                "reason": (
                    f"'{dept}' 검색어로 조회된 의료기관입니다. "
                    "실제 진료과는 방문 전 확인하세요."
                ),
                "source": "카카오 로컬 API",
            }

    records = list(places.values())

    if nearby:
        records.sort(
            key=lambda item: (
                item["distance_m"] is None,
                item["distance_m"] or 0,
            )
        )

    response["hospitals"] = records[:max_results]

    if not records:
        response["notice"] = (
            "조건에 맞는 병원을 찾지 못했습니다. "
            "지역이나 진료과를 바꿔 검색해 주세요."
        )
    elif nearby:
        response["notice"] = (
            "표시된 거리는 직선거리입니다. "
            "진료과·운영시간·접수 가능 여부는 "
            "병원에 직접 확인하세요."
        )
    else:
        response["notice"] = (
            "지역명 기반 검색 결과입니다. "
            "가까운 순서는 아니며 실제 진료과·"
            "운영시간을 확인하세요."
        )

    return response