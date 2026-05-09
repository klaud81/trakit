"""뉴스 페이지 인증 서비스.

Google Sheet AQ1 셀의 base64 인코딩된 비밀번호를 디코딩해 비교.
시트만 수정하면 비밀번호 갱신 가능 (배포/코드 변경 불필요).
"""
from __future__ import annotations
import base64
import csv
import io
import logging
from datetime import datetime
from typing import Optional
import requests
from config import GOOGLE_SHEET_URL

logger = logging.getLogger(__name__)

_AUTH_CACHE: Optional[str] = None  # 디코딩된 평문 비밀번호
_AUTH_CACHE_TIME: Optional[datetime] = None
_AUTH_CACHE_TTL_SEC = 300  # 5분

# AQ 열 = 0-indexed 42 (A=0..Z=25, AA=26..AQ=42)
_AQ_INDEX = 42


def _load_password() -> Optional[str]:
    """시트 AQ1 cell 의 base64 → 평문 디코딩. 5분 캐시."""
    global _AUTH_CACHE, _AUTH_CACHE_TIME
    if _AUTH_CACHE and _AUTH_CACHE_TIME:
        if (datetime.now() - _AUTH_CACHE_TIME).total_seconds() < _AUTH_CACHE_TTL_SEC:
            return _AUTH_CACHE
    try:
        r = requests.get(GOOGLE_SHEET_URL, timeout=15)
        r.raise_for_status()
        r.encoding = "utf-8"
        reader = csv.reader(io.StringIO(r.text))
        rows = list(reader)
        if not rows or len(rows[0]) <= _AQ_INDEX:
            logger.warning("뉴스 비밀번호 셀(AQ1) 없음")
            return None
        b64 = rows[0][_AQ_INDEX].strip()
        if not b64:
            return None
        plain = base64.b64decode(b64).decode("utf-8").strip()
        _AUTH_CACHE = plain
        _AUTH_CACHE_TIME = datetime.now()
        logger.info("🔑 뉴스 비밀번호 캐시 갱신")
        return plain
    except Exception as e:
        logger.warning(f"뉴스 비밀번호 로드 실패: {e}")
        return _AUTH_CACHE  # 실패 시 stale 캐시 반환


def verify_password(input_password: str) -> bool:
    expected = _load_password()
    if not expected:
        return False
    return input_password == expected
