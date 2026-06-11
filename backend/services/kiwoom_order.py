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
# 모의계좌 초기 원금(시드). 손익 계산 기준 — entr(예수금)은 결제 후 실현이익을 흡수해
# 원금 기준으로 못 쓰므로 고정값 사용. 계좌 시드가 다르면 VI_ARB_MOCK_SEED 로 override.
import os as _os
_MOCK_SEED = int(_os.getenv("VI_ARB_MOCK_SEED", "500000000"))


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


def _won(s) -> int:
    """0-padding 부호 12자리 문자열 → 정수 (int() 가 leading-zero/부호 처리)."""
    try:
        return int(str(s).strip() or 0)
    except (TypeError, ValueError):
        return 0


def get_balance() -> dict:
    """모의계좌 평가현황 조회 (kt00004): 예수금·평가액·손익·보유종목."""
    if not _is_mock():
        return {"ok": False, "reason": "모의 도메인 아님"}
    token = _order_token()
    if not token:
        return {"ok": False, "reason": "토큰 없음"}
    try:
        r = _post("/api/dostk/acnt", {"qry_tp": "0", "dmst_stex_tp": "KRX"},
                  {"authorization": f"Bearer {token}", "api-id": "kt00004"})
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    holdings = [{"code": (h.get("stk_cd") or "")[-6:], "name": h.get("stk_nm", ""),
                 "qty": _won(h.get("rmnd_qty")), "avg": _won(h.get("avg_prc")),
                 "cur": _won(h.get("cur_prc")), "evlt": _won(h.get("evlt_amt")),
                 "pl": _won(h.get("pl_amt")), "pl_rt": h.get("pl_rt", "")}
                for h in (r.get("stk_acnt_evlt_prst") or [])]
    stock_value = _won(r.get("tot_est_amt"))      # 총평가금액(현재가)
    buy_amount = _won(r.get("tot_pur_amt"))        # 총매입금액
    eval_pl = stock_value - buy_amount             # 평가손익(미실현)
    eval_pl_rt = round(eval_pl / buy_amount * 100, 2) if buy_amount else 0.0
    # 모의계좌는 tdy_lspft(실현손익)을 0으로만 줌 → 직접 계산:
    #   총손익 = 추정예탁자산 − 고정원금(시드), 실현손익 = 총손익 − 미실현평가
    #   ※ entr(예수금)은 결제 후 실현이익을 흡수해 기준으로 못 씀 → 고정 _MOCK_SEED 사용
    base_deposit = _won(r.get("entr"))             # 현재 예수금(표시용)
    est_asset = _won(r.get("prsm_dpst_aset_amt"))  # 추정예탁자산(현금+평가)
    total_pl = est_asset - _MOCK_SEED              # 전체 손익(실현+미실현) vs 원금
    realized_pl = total_pl - eval_pl               # 실현손익 = 전체 − 미실현
    realized_pl_rt = round(realized_pl / _MOCK_SEED * 100, 2) if _MOCK_SEED else 0.0
    total_pl_rt = round(total_pl / _MOCK_SEED * 100, 2) if _MOCK_SEED else 0.0
    return {"ok": str(r.get("return_code", "0")) in ("0", "None"),
            "account": _MOCK.get("account", ""),
            "deposit": base_deposit, "d2_deposit": _won(r.get("d2_entra")),
            "stock_value": stock_value, "asset_value": _won(r.get("aset_evlt_amt")),
            "buy_amount": buy_amount, "est_asset": est_asset,
            "eval_pl": eval_pl, "eval_pl_rt": eval_pl_rt,            # 미실현 평가손익
            "realized_pl": realized_pl, "realized_pl_rt": realized_pl_rt,  # 실현손익(계산)
            "total_pl": total_pl, "total_pl_rt": total_pl_rt,       # 전체 손익(계산)
            "today_pl": _won(r.get("tdy_lspft")),                   # 키움 원본(모의=0)
            "today_pl_rt": r.get("tdy_lspft_rt", ""), "holdings": holdings,
            "return_msg": r.get("return_msg", "")}


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


_SELL_THROTTLE_SEC = 0.3   # 주문 간 간격 (Kiwoom 429 레이트리밋 회피, ~3건/초)


def sell_all() -> dict:
    """모의계좌 전 보유종목 시장가 일괄매도 (보유수량 전량).
    Kiwoom 429(Too Many Requests) 회피: 주문 간 throttle + 429 시 1회 재시도."""
    if not _is_mock():
        return {"ok": False, "reason": "모의 도메인 아님", "results": []}
    bal = get_balance()
    if not bal.get("ok"):
        return {"ok": False, "reason": bal.get("reason", "잔고조회 실패"), "results": []}
    holds = [h for h in bal.get("holdings", []) if (h.get("qty") or 0) > 0]
    results = []
    for i, h in enumerate(holds):
        if i:
            time.sleep(_SELL_THROTTLE_SEC)
        r = place_order(h["code"], "sell", qty=h["qty"], price=None, exchange="KRX")  # 시장가
        if not r.get("ok") and "429" in str(r.get("reason", "")):
            time.sleep(1.0)   # 레이트리밋 → 잠시 후 1회 재시도
            r = place_order(h["code"], "sell", qty=h["qty"], price=None, exchange="KRX")
        results.append({"code": h["code"], "name": h.get("name"), "qty": h["qty"],
                        "ok": r.get("ok"), "ord_no": r.get("ord_no"), "reason": r.get("reason", "")})
    sold = sum(1 for x in results if x["ok"])
    logger.info(f"💸 일괄매도: {sold}/{len(results)} 종목 접수")
    return {"ok": True, "sold": sold, "total": len(results), "results": results}
