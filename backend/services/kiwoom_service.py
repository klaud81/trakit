"""키움증권 REST API 서비스 (KR 데이터 자체 수집).

100m1s 미러를 대체하기 위한 키움 OpenAPI(신버전, REST) 연동.
1단계: 접근토큰 발급/캐시. 시세·일봉·순위 TR 은 토큰 검증 후 추가 예정.

토큰 처리는 KIS(price_service) 패턴을 그대로 따른다:
  메모리 캐시 → 디스크 캐시(.kiwoom_token.json) → 신규 발급.
재시작 후에도 만료 전이면 재사용하여 불필요한 재발급을 줄인다.

키움 토큰 발급 응답 형식 (KIS 와 다름):
  POST {base}/oauth2/token
  body: {"grant_type":"client_credentials","appkey":..,"secretkey":..}
  resp: {"token":..,"token_type":"bearer","expires_dt":"YYYYMMDDHHMMSS",
         "return_code":0,"return_msg":".."}
"""
from __future__ import annotations
import asyncio
import json
import logging
import ssl
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from config import (
    KIWOOM_APP_KEY,
    KIWOOM_APP_SECRET,
    KIWOOM_MODE,
    KIWOOM_BASE_URL,
    DATA_DIR,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 토큰 캐시 (메모리 + 디스크 영속화) — KIS 와 동일 전략
_kiwoom_token: Optional[str] = None
_kiwoom_token_expires: Optional[datetime] = None
_KIWOOM_TOKEN_FILE = DATA_DIR / ".kiwoom_token.json"


def _load_token_from_disk() -> bool:
    """디스크에서 토큰 로드. 유효하면 메모리 캐시에 적재."""
    global _kiwoom_token, _kiwoom_token_expires
    try:
        if not _KIWOOM_TOKEN_FILE.exists():
            return False
        data = json.loads(_KIWOOM_TOKEN_FILE.read_text())
        expires = datetime.fromisoformat(data["expires_at"])
        if datetime.now() >= expires:
            return False  # 만료됨
        _kiwoom_token = data["token"]
        _kiwoom_token_expires = expires
        logger.info(f"🔑 키움 토큰 디스크 로드 (만료: {expires.strftime('%Y-%m-%d %H:%M')})")
        return True
    except Exception as e:
        logger.warning(f"키움 토큰 디스크 로드 실패: {e}")
        return False


def _save_token_to_disk(token: str, expires: datetime) -> None:
    """토큰을 디스크에 저장 (재시작 시 재사용)."""
    try:
        _KIWOOM_TOKEN_FILE.write_text(json.dumps({
            "token": token,
            "expires_at": expires.isoformat(),
        }))
    except Exception as e:
        logger.warning(f"키움 토큰 디스크 저장 실패: {e}")


def _parse_expires(expires_dt: str | None) -> datetime:
    """키움 expires_dt('YYYYMMDDHHMMSS') 파싱. 실패 시 23h 후."""
    if expires_dt:
        try:
            return datetime.strptime(expires_dt, "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return datetime.now() + timedelta(hours=23)


def get_token(force: bool = False) -> Optional[str]:
    """키움 REST 접근토큰 발급 (디스크 캐시). 실패 시 None."""
    global _kiwoom_token, _kiwoom_token_expires
    if not force:
        # 1) 메모리 캐시
        if _kiwoom_token and _kiwoom_token_expires and datetime.now() < _kiwoom_token_expires:
            return _kiwoom_token
        # 2) 디스크 캐시
        if _load_token_from_disk():
            return _kiwoom_token
    # 3) 신규 발급
    if not KIWOOM_APP_KEY or not KIWOOM_APP_SECRET:
        logger.warning("키움 앱키/시크릿 미설정 (KIWOOM_APP_KEY / KIWOOM_APP_SECRET)")
        return None
    try:
        resp = requests.post(
            f"{KIWOOM_BASE_URL}/oauth2/token",
            json={
                "grant_type": "client_credentials",
                "appkey": KIWOOM_APP_KEY,
                "secretkey": KIWOOM_APP_SECRET,
            },
            headers={"Content-Type": "application/json;charset=UTF-8"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        # 키움은 정상 시 return_code=0. 토큰 필드명은 환경에 따라 token / access_token.
        if data.get("return_code") not in (0, None):
            logger.warning(f"키움 토큰 발급 거부: {data.get('return_code')} {data.get('return_msg')}")
            return None
        token = data.get("token") or data.get("access_token")
        if not token:
            logger.warning(f"키움 토큰 응답에 token 없음: {data}")
            return None
        _kiwoom_token = token
        _kiwoom_token_expires = _parse_expires(data.get("expires_dt"))
        _save_token_to_disk(_kiwoom_token, _kiwoom_token_expires)
        logger.info(
            f"🔑 키움 토큰 신규 발급 ({KIWOOM_MODE}, "
            f"만료: {_kiwoom_token_expires.strftime('%Y-%m-%d %H:%M')})"
        )
        return _kiwoom_token
    except Exception as e:
        logger.warning(f"키움 토큰 발급 실패: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────
# TR 호출 (국내주식). 키움 REST 는 카테고리별 경로 + api-id 헤더로 구분.
#   차트:  POST /api/dostk/chart   (ka10081 주식일봉차트조회요청)
# ─────────────────────────────────────────────────────────────────────────

def _tr_post(path: str, api_id: str, body: dict,
             cont_yn: str = "N", next_key: str = "") -> Optional[dict]:
    """키움 TR POST. 실패/거부 시 None. 성공 시 응답 JSON(dict)."""
    token = get_token()
    if not token:
        return None
    try:
        resp = requests.post(
            f"{KIWOOM_BASE_URL}{path}",
            json=body,
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {token}",
                "api-id": api_id,
                "cont-yn": cont_yn,
                "next-key": next_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("return_code") not in (0, None):
            logger.warning(f"키움 {api_id} 거부: {data.get('return_code')} {data.get('return_msg')}")
            return None
        return data
    except Exception as e:
        logger.warning(f"키움 {api_id} 호출 실패: {e}")
        return None


def _to_num(v) -> float:
    """키움 수치 문자열(부호 +/-, 콤마 포함 가능) → 절댓값 숫자."""
    if v is None:
        return 0.0
    s = str(v).replace(",", "").strip().lstrip("+-")
    try:
        return float(s)
    except ValueError:
        return 0.0


def get_daily_chart_raw(code: str, base_dt: str | None = None,
                        adj: bool = True) -> Optional[dict]:
    """ka10081 주식일봉차트조회 원본 응답(dict) 반환 (필드 검증용)."""
    if base_dt is None:
        base_dt = datetime.now(KST).strftime("%Y%m%d")
    body = {
        "stk_cd": code,
        "base_dt": base_dt,
        "upd_stkpc_tp": "1" if adj else "0",  # 수정주가구분
    }
    return _tr_post("/api/dostk/chart", "ka10081", body)


# ka10081 응답 후보 키 (환경/문서 버전에 따라 변동 → 다중 후보로 방어)
_CHART_LIST_KEYS = ("stk_dt_pole_chart_qry", "stk_dt_pole_chart_qry_list", "chart", "output")
_F = {
    "d":  ("dt", "stck_bsop_date", "date"),
    "o":  ("open_pric", "open_prc", "stck_oprc", "open"),
    "h":  ("high_pric", "high_prc", "stck_hgpr", "high"),
    "l":  ("low_pric", "low_prc", "stck_lwpr", "low"),
    "c":  ("cur_prc", "close_pric", "stck_clpr", "close"),
    "v":  ("trde_qty", "acml_vol", "volume"),
    "ta": ("trde_prica", "acml_tr_pbmn", "trade_amount"),
}


def _pick(item: dict, keys) -> object:
    for k in keys:
        if k in item:
            return item[k]
    return None


def get_daily_chart(code: str, base_dt: str | None = None,
                    adj: bool = True) -> Optional[list[dict]]:
    """ka10081 → dailybars rows 스키마 [{d,o,h,l,c,v,ta}, ...] 정규화."""
    data = get_daily_chart_raw(code, base_dt, adj)
    if not data:
        return None
    rows_raw = None
    for k in _CHART_LIST_KEYS:
        if isinstance(data.get(k), list):
            rows_raw = data[k]
            break
    if rows_raw is None:
        logger.warning(f"ka10081 응답에 차트 리스트 없음. keys={list(data.keys())}")
        return None
    out = []
    for it in rows_raw:
        d = _pick(it, _F["d"])
        if not d:
            continue
        ds = str(d)
        # 날짜 YYYYMMDD → YYYY-MM-DD (기존 dailybars 스키마 형식)
        if len(ds) == 8 and ds.isdigit():
            ds = f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
        out.append({
            "d": ds,
            "o": int(_to_num(_pick(it, _F["o"]))),
            "h": int(_to_num(_pick(it, _F["h"]))),
            "l": int(_to_num(_pick(it, _F["l"]))),
            "c": int(_to_num(_pick(it, _F["c"]))),
            "v": int(_to_num(_pick(it, _F["v"]))),
            # 키움 trde_prica 는 백만원 단위 → 원 단위(raw won)로 환산 (기존 ta 스키마)
            "ta": int(_to_num(_pick(it, _F["ta"])) * 1_000_000),
        })
    # 키움은 최신일 우선(내림차순) 반환 → 기존 dailybars 는 과거→현재 오름차순. 정렬 통일.
    out.sort(key=lambda r: r["d"])
    return out


def get_today_trade_amount(code: str) -> Optional[int]:
    """오늘(KST) 거래대금(원) — ka10081 일봉의 당일 행 trde_prica. 없으면 None.

    조건검색(ka10172) 응답의 거래대금(field 14)이 영구 부재라 ka10081 로 정합화.
    (100m1s kiwoom_client.get_today_trade_amount 와 동일 근거)
    """
    rows = get_daily_chart(code)
    if not rows:
        return None
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for r in reversed(rows):  # 최신이 끝 → 뒤에서 탐색
        if r["d"] == today:
            return r["ta"]
    return None


# ─────────────────────────────────────────────────────────────────────────
# 조건검색 (WebSocket). 100m1s kiwoom_client 포팅.
#   호출 순서: LOGIN → CNSRLST(ka10171 목록) → CNSRREQ(ka10172 실행)
#   wss://{domain}:10000/api/dostk/websocket
# ─────────────────────────────────────────────────────────────────────────

def _ws_url() -> str:
    domain = KIWOOM_BASE_URL.replace("https://", "").replace("http://", "")
    return f"wss://{domain}:10000/api/dostk/websocket"


async def _ws_connect():
    try:
        import websockets
    except ImportError:
        raise RuntimeError("websockets 패키지 필요: pip install websockets")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return websockets.connect(_ws_url(), ssl=ctx, open_timeout=15)


async def _ws_condition_list(token: str) -> list:
    async with await _ws_connect() as ws:
        await ws.send(json.dumps({"trnm": "LOGIN", "token": token}))
        login = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if login.get("return_code") != 0:
            raise RuntimeError(f"WebSocket LOGIN 실패: {login}")
        await ws.send(json.dumps({"trnm": "CNSRLST"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("return_code") != 0:
            raise RuntimeError(f"조건검색 목록 조회 실패: {resp}")
        return resp.get("data", [])


async def _ws_condition_search(token: str, seq, search_type: str = "0", stex_tp: str = "K") -> list:
    async with await _ws_connect() as ws:
        await ws.send(json.dumps({"trnm": "LOGIN", "token": token}))
        login = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if login.get("return_code") != 0:
            raise RuntimeError(f"WebSocket LOGIN 실패: {login}")
        await ws.send(json.dumps({"trnm": "CNSRLST"}))  # 검색 전 필수
        await asyncio.wait_for(ws.recv(), timeout=10)
        req = {
            "trnm": "CNSRREQ", "seq": str(seq), "search_type": search_type,
            "stex_tp": stex_tp, "cont_yn": "N", "next_key": "",
        }
        await ws.send(json.dumps(req))
        out = []
        while True:
            try:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            except (TimeoutError, asyncio.TimeoutError):
                break
            if r.get("return_code") not in (0, None):
                raise RuntimeError(f"조건검색 실패: {r}")
            data = r.get("data", [])
            if isinstance(data, list):
                out.extend(data)
            if r.get("cont_yn") == "Y" and r.get("next_key"):
                await ws.send(json.dumps({**req, "cont_yn": "Y", "next_key": r["next_key"]}))
            else:
                break
        return out


def condition_list() -> list:
    """조건검색식 목록 [[seq, name], ...] (동기). 토큰 없으면 []."""
    token = get_token()
    if not token:
        return []
    return asyncio.run(_ws_condition_list(token))


def condition_search(seq, **kwargs) -> list:
    """조건검색 실행 결과 [{'9001':코드, '302':명, '10':현재가, ...}, ...] (동기)."""
    token = get_token()
    if not token:
        return []
    return asyncio.run(_ws_condition_search(token, seq, **kwargs))


if __name__ == "__main__":
    # 토큰 발급 검증용 단독 실행: python -m services.kiwoom_service
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    print(f"[키움] mode={KIWOOM_MODE} base={KIWOOM_BASE_URL}")
    print(f"[키움] app_key set={bool(KIWOOM_APP_KEY)} secret set={bool(KIWOOM_APP_SECRET)}")
    tok = get_token(force=True)
    if tok:
        masked = tok[:6] + "…" + tok[-4:] if len(tok) > 12 else "***"
        exp = _kiwoom_token_expires.strftime("%Y-%m-%d %H:%M") if _kiwoom_token_expires else "?"
        print(f"✅ 토큰 발급 성공: {masked} (만료 {exp})")
    else:
        print("❌ 토큰 발급 실패 — 위 로그 확인")
