"""익명 데모용 임시 다운로드 링크.

파일 이름만으로 제3자가 내려받지 못하도록 HMAC 서명 + 만료 시간을 사용한다.
로그인 사용자별 접근 제어를 대체하지는 않으며 공개 서비스 전 인증이 필요하다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote

# 환경변수로 제공하면 재기동 후에도 링크가 유효하고, 없으면 프로세스 재기동 시 무효화된다.
# .env는 main.py import 후에 로드되므로 비밀값은 매 서명 시점에 가져온다.
_PROCESS_SECRET = secrets.token_bytes(32)


def _secret() -> bytes:
    return (os.getenv("MEDIHAN_DOWNLOAD_SECRET") or "").encode("utf-8") or _PROCESS_SECRET


TOKEN_TTL_SECONDS = 3600
REPORT_RETENTION_SECONDS = 24 * 3600
ALLOWED_SUFFIXES = {".pdf", ".docx", ".png"}


def _digest(filename: str, expires_at: int) -> str:
    message = f"{filename}:{expires_at}".encode("utf-8")
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


def sign_download_url(filename: str) -> str:
    safe_name = Path(filename).name
    if safe_name != filename or Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("올바르지 않은 보고서 이름입니다.")
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    token = f"{expires_at}.{_digest(safe_name, expires_at)}"
    return f"/api/download/{quote(safe_name)}?token={token}"


def verify_download_token(filename: str, token: str) -> bool:
    if not token or Path(filename).name != filename:
        return False
    try:
        stamp, signature = token.split(".", 1)
        expires_at = int(stamp)
        now = int(time.time())
        if expires_at < now or expires_at > now + TOKEN_TTL_SECONDS:
            return False
        return hmac.compare_digest(_digest(filename, expires_at), signature)
    except (ValueError, TypeError):
        return False


def cleanup_report_files(report_dir: Path) -> int:
    """서버가 생성한 오래된 보고서만 삭제한다."""
    if not report_dir.exists():
        return 0
    threshold = time.time() - REPORT_RETENTION_SECONDS
    removed = 0
    for file in report_dir.iterdir():
        if (file.is_file() and file.name.startswith("medihan_report_")
                and file.suffix.lower() in ALLOWED_SUFFIXES
                and file.stat().st_mtime < threshold):
            file.unlink(missing_ok=True)
            removed += 1
    return removed
