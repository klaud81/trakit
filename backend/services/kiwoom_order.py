"""Kiwoom 모의 주문 — VI 종목 체결 시도 (rq-01 Phase: 모의 한정).

⚠️ 안전: 주문은 **모의 도메인(mockapi.kiwoom.com)** 에서만 전송. 실서버 도메인이면 거부.
   `VI_ARB_ORDER=true` 일 때만 동작. 상시모의투자 계좌(예: 81277130)의 app key/secret 사용.

문서 확인 (docs/kiwoom-rest-api.pdf):
  - 매수 kt10000 / 매도 kt10001, POST /api/dostk/ordr
  - Body: dmst_stex_tp(KRX/NXT/SOR), stk_cd, ord_qty, ord_uv, trde_tp(0보통/3시장가), cond_uv
  - 계좌는 토큰에 귀속(body 계좌번호 없음). 모의 도메인 KRX만 지원.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

from config import KIWOOM_ENVS, VI_ARB_ORDER, VI_ARB_ORDER_QTY

logger = logging.getLogger(__name__)
_token: tuple[str, float] | None = None  # (token, expire_epoch)
_MOCK = KIWOOM_ENVS["mock"]               # 주문은 항상 모의 환경만 사용 (안전)


def _is_mock() -> bool:
    return "mock" in (_MOCK.get("base_url") or "").lower()


def _post(path: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        f"{_MOCK['base_url']}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json;charset=UTF-8", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _order_token() -> str | None:
    """모의 도메인 토큰 발급/캐시 (실서버와 분리)."""
    global _token
    if _token and _token[1] > time.time() + 60:
        return _token[0]
    if not (_MOCK.get("app_key") and _MOCK.get("app_secret")):
        return None
    try:
        r = _post("/oauth2/token",
                  {"grant_type": "client_credentials", "appkey": _MOCK["app_key"],
                   "secretkey": _MOCK["app_secret"]}, {})
        tok = r.get("token") or r.get("access_token")
        if tok:
            _token = (tok, time.time() + 3600)
            return tok
    except Exception as e:
        logger.warning(f"모의 주문 토큰 발급 실패: {e}")
    return None


def get_account() -> dict:
    """현재 토큰의 모의계좌번호 조회 (ka00001). 계좌는 토큰(app key)에 귀속됨."""
    if not _is_mock():
        return {"ok": False, "reason": "모의 도메인 아님"}
    token = _order_token()
    if not token:
        return {"ok": False, "reason": "토큰 없음"}
    try:
        r = _post("/api/dostk/acnt", {},
                  {"authorization": f"Bearer {token}", "api-id": "ka00001"})
        acct = r.get("acctNo") or ""
        return {"ok": str(r.get("return_code")) == "0", "acctNo": acct}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def verify_account() -> dict:
    """토큰 계좌가 mock 환경 account 와 일치하는지 검증 (주문 전 안전확인)."""
    expected = _MOCK.get("account", "")
    res = get_account()
    acct = res.get("acctNo", "")
    res["expected"] = expected
    res["match"] = bool(expected) and acct.startswith(expected)
    if expected and not res["match"]:
        logger.warning(f"⚠️ 모의계좌 불일치: 토큰계좌={acct} 설정={expected}")
    return res


def place_order(stk_cd: str, side: str = "buy", qty: int | None = None,
                price: int | None = None, exchange: str = "KRX") -> dict:
    """모의 매수/매도 주문. 안전게이트 통과 시에만 전송.

    side: buy|sell. price=None → 시장가. 반환: {ok, ord_no?, reason?}.
    """
    if not VI_ARB_ORDER:
        return {"ok": False, "reason": "VI_ARB_ORDER=false (주문 비활성)"}
    if not _is_mock():
        logger.error(f"🚫 주문 거부: 모의 도메인 아님 ({KIWOOM_ORDER_BASE_URL})")
        return {"ok": False, "reason": "실서버 도메인 — 주문 차단"}
    token = _order_token()
    if not token:
        return {"ok": False, "reason": "토큰 없음"}
    api_id = "kt10000" if side == "buy" else "kt10001"
    body = {
        "dmst_stex_tp": exchange, "stk_cd": stk_cd,
        "ord_qty": str(qty or VI_ARB_ORDER_QTY),
        "ord_uv": "" if price is None else str(price),
        "trde_tp": "3" if price is None else "0",   # 3:시장가 / 0:보통(지정가)
        "cond_uv": "",
    }
    try:
        r = _post("/api/dostk/ordr", body,
                  {"authorization": f"Bearer {token}", "api-id": api_id})
        ok = str(r.get("return_code")) == "0"
        return {"ok": ok, "ord_no": r.get("ord_no"), "side": side, "stk_cd": stk_cd,
                "qty": body["ord_qty"], "reason": r.get("return_msg", "")}
    except Exception as e:
        logger.warning(f"모의 주문 실패 ({side} {stk_cd}): {e}")
        return {"ok": False, "reason": str(e)}
