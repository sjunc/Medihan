
"""질병관리청 국가건강정보포털 OpenAPI 클라이언트.

TOKEN과 cntntsSn을 이용해 공식 건강정보를 조회한다.
환자 의료문서와 개인정보는 이 API에 전송하지 않는다.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
import xml.etree.ElementTree as ET

from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

API_URL = "https://api.kdca.go.kr/api/provide/healthInfo"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SUCCESS_CODES = {"S001", "0", "00"}


class KDCAApiError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 502,
    ):
        super().__init__(message)
        self.status_code = status_code


class _NoRedirect(HTTPRedirectHandler):
    """HTTPS 요청이 다른 서버로 리디렉션되는 것을 차단한다."""

    def redirect_request(
        self, req, fp, code, msg, headers, newurl,
    ):
        return None


class _HTMLToText(HTMLParser):
    """XML CDATA 안의 HTML을 표시용 일반 텍스트로 변환한다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {
            "p", "br", "div", "li",
            "h1", "h2", "h3", "tr",
        }:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        value = "".join(self.parts)
        return "\n".join(
            line.strip()
            for line in value.splitlines()
            if line.strip()
        )


def _plain_text(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    return unescape(parser.text())


def _tag(element: ET.Element) -> str:
    name = element.tag.rsplit("}", 1)[-1].upper()
    return re.sub(r"[^A-Z0-9]", "", name)


def _direct_value(
    element: ET.Element,
    *names: str,
) -> str:
    wanted = {
        re.sub(r"[^A-Z0-9]", "", name.upper())
        for name in names
    }

    for child in element:
        if _tag(child) in wanted:
            return "".join(child.itertext()).strip()

    return ""


def _first_element(
    root: ET.Element,
    name: str,
) -> ET.Element | None:
    for node in root.iter():
        if _tag(node) == name.upper():
            return node
    return None


def parse_kdca_xml(
    xml_data: bytes,
    content_id: str,
) -> dict:
    """명세서의 HEAD, CODE, MESSAGE, SV를 파싱한다."""

    upper_data = xml_data.upper()

    if (
        b"<!DOCTYPE" in upper_data
        or b"<!ENTITY" in upper_data
    ):
        raise KDCAApiError(
            "지원하지 않는 XML 선언입니다."
        )

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        raise KDCAApiError(
            "질병관리청 응답을 XML로 해석할 수 없습니다."
        ) from exc

    head = _first_element(root, "HEAD")

    code = (
        _direct_value(head, "CODE")
        if head is not None else ""
    )
    message = (
        _direct_value(head, "MESSAGE")
        if head is not None else ""
    )

    if not code:
        raise KDCAApiError(
            "응답에 결과 코드가 없습니다."
        )

    if code not in SUCCESS_CODES:
        errors = {
            "20": "조회가 거부되었습니다. 콘텐츠 권한을 확인하세요.",
            "21": "일시적으로 사용할 수 없는 API 키입니다.",
            "22": "API 호출 횟수 제한을 초과했습니다.",
            "30": "등록되지 않은 API 키입니다.",
            "31": "API 이용 기간이 만료되었습니다.",
            "32": "등록되지 않은 서버 IP입니다.",
            "33": "서명되지 않은 호출입니다.",
            "3": "해당 콘텐츠를 찾지 못했습니다.",
        }

        raise KDCAApiError(
            f"질병관리청 오류 {code}: "
            f"{errors.get(code, '조회 실패')}"
        )
    # 실제 응답은 <svc>, 명세서 예시는 <SV> 형태.
    sv = _first_element(root, "SVC")

    if sv is None:
        sv = _first_element(root, "SV")

    if sv is None:
        raise KDCAApiError(
            "응답에 콘텐츠 본문이 없습니다."
        )

    title = _direct_value(
        sv,
        "CNTNTSSJ",
        "CNTNTSNM",
        "CNTNTS_NM",
    )
    if title.isdecimal():
        title = ""

    sections = []

    for node in sv.iter():
        name = _direct_value(
            node,
            "CNTNTS_CL_NM",
            "CNTNTSCLNM",
        )

        body = _direct_value(
            node,
            "CNTNTS_CL_CN",
            "CNTNTSCLCN",
        )

        if not (name or body):
            continue

        if len(sections) >= 40:
            break

        sections.append({
            "title": name or "건강정보",
            "text": _plain_text(body)[:30000],
        })

    # 일부 응답에서 항목이 평면 구조로 올 경우 대비.
    if not sections:
        title_nodes = [
            node for node in sv.iter()
            if _tag(node) == "CNTNTSCLNM"
        ]
        text_nodes = [
            node for node in sv.iter()
            if _tag(node) == "CNTNTSCLCN"
        ]

        for name_node, text_node in zip(
            title_nodes,
            text_nodes,
        ):
            sections.append({
                "title": "".join(
                    name_node.itertext()
                ).strip(),
                "text": _plain_text(
                    "".join(text_node.itertext())
                )[:30000],
            })

    return {
        "content_id": content_id,
        "title": title,
        "source": "질병관리청 국가건강정보포털",
        "code": code,
        "message": message,
        "sections": sections,
    }


def fetch_kdca_content(content_id: str) -> dict:
    """콘텐츠 ID를 검증하고 서버에서 공식 API를 호출한다."""

    if not re.fullmatch(
        r"[0-9]{1,10}",
        str(content_id),
    ):
        raise KDCAApiError(
            "콘텐츠 ID는 1~10자리 숫자여야 합니다.",
            400,
        )

    key = os.getenv("KDCA_API_KEY", "").strip()

    if not key:
        raise KDCAApiError(
            "KDCA_API_KEY가 설정되지 않았습니다.",
            503,
        )

    # 직접 인코딩한 값을 넣지 말고 원본 키를 사용한다.
    # urlencode가 TOKEN을 안전하게 URL 인코딩한다.
    params = urlencode({
        "TOKEN": key,
        "cntntsSn": str(content_id),
    })

    request = Request(
        f"{API_URL}?{params}",
        headers={
            "Accept": "application/xml, text/xml",
        },
        method="GET",
    )

    # 기본 인증서 검증 및 호스트명 검증은 유지한다.
    ssl_context = ssl.create_default_context()

    # KDCA 서버의 구형 TLS 재협상 방식과 호환.
    # 이 옵션은 KDCA 전용 HTTPSHandler에만 적용된다.
    ssl_context.options |= ssl.OP_LEGACY_SERVER_CONNECT

    # HTTPS 컨텍스트를 KDCA 요청 전용으로 구성.
    # 다른 서버의 SSL 설정은 변경하지 않는다.
    opener = build_opener(
        _NoRedirect(),
        HTTPSHandler(context=ssl_context),
    )

    try:
        with opener.open(
            request,
            timeout=30,
        ) as response:
            xml_data = response.read(
                MAX_RESPONSE_BYTES + 1
            )

    except HTTPError as exc:
        raise KDCAApiError(
            f"질병관리청 서버 HTTP {exc.code} 오류"
        ) from None

    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)

        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = "SSL 인증서 검증 실패"

        elif isinstance(reason, ssl.SSLError):
            detail = "SSL/TLS 연결 오류"

        elif isinstance(reason, (socket.timeout, TimeoutError)):
            detail = "서버 응답 시간 초과 (30초)"

        elif isinstance(reason, socket.gaierror):
            detail = "DNS 주소 확인 실패"

        elif isinstance(reason, ConnectionRefusedError):
            detail = "서버 연결 거부"

        else:
            detail = (
                "네트워크 연결 오류 "
                f"({type(reason).__name__})"
            )

        raise KDCAApiError(
            f"질병관리청 API 호출 실패: {detail}"
        ) from None

    if len(xml_data) > MAX_RESPONSE_BYTES:
        raise KDCAApiError(
            "응답 크기가 제한을 초과했습니다."
        )

    return parse_kdca_xml(
        xml_data,
        str(content_id),
    )
