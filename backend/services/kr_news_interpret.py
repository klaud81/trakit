"""KR 뉴스 해석(뉴지) — Gemini 분석.

100m1s-homepage/scripts/cafe-scraper/main.py 의 gemini_analyze_news / html_to_text
를 trakit 로 복사·적응. 뉴스 URL → 본문 fetch → Gemini → 호재/악재/강도 판단.

차이: 키/모델을 config(GEMINI_API_KEY, GEMINI_MODEL)에서 읽음. 네이버 검색 API로
얻은 기사 URL 에 적용하는 용도(카페 스크래핑 playwright 불필요).

판단 schema (원본 동일): {summary, judgment(호재/악재/중립), strength(강/중/약), reasoning}
참고: strength 는 LLM 자가보고 — calibration 0. 거짓 정밀성 회피로 % 대신 카테고리.
"""
from __future__ import annotations
import json
import re
import urllib.request
import logging

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)


def html_to_text(html: str) -> str:
    """간단한 HTML → 텍스트. BeautifulSoup 없이. (100m1s 복사)"""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def analyze_news(news_url: str, news_title_hint: str = "") -> dict:
    """Gemini로 뉴스 요약 + 호재/악재/강도 판단. API 키 없으면 mock.
    (100m1s gemini_analyze_news 복사 — 키/모델만 config 사용)
    """
    if not GEMINI_API_KEY:
        return {
            "summary": f"[mock] {news_title_hint or '(요약 미생성 — API 키 없음)'}",
            "judgment": "중립", "strength": "약", "reasoning": "API 키 없음",
        }
    try:
        # 1) 뉴스 본문 fetch
        req = urllib.request.Request(news_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            news_html = resp.read().decode("utf-8", errors="ignore")
        news_text = html_to_text(news_html)[:3000]

        # 2) Gemini 호출
        prompt = f"""당신은 한국 주식 시장 분석 에이전트입니다.
종목 컨텍스트: {news_title_hint}

다음 뉴스를 한국 주식 시장 관점에서 분석하세요:

URL: {news_url}
본문(일부): {news_text}

판단:
- judgment: "호재" / "악재" / "중립"
- strength: 신호의 강도 — "강" / "중" / "약" 셋 중 하나
  · 강 = 명확하고 즉시 영향, 다중 출처/데이터 뒷받침
  · 중 = 영향 가능성 있으나 확정적이지 않음
  · 약 = 단서 수준, 추측 동반

다음 JSON 형식으로만 답하세요:
{{"summary": "3-5줄 한국어 요약", "judgment": "호재"|"악재"|"중립", "strength": "강"|"중"|"약", "reasoning": "1-2줄 판단 근거"}}"""

        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
        }).encode("utf-8")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        strength = parsed.get("strength", "중")
        if strength not in ("강", "중", "약"):
            strength = "중"
        return {
            "summary": parsed.get("summary", ""),
            "judgment": parsed.get("judgment", "중립"),
            "strength": strength,
            "reasoning": parsed.get("reasoning", ""),
        }
    except Exception as e:
        logger.warning(f"Gemini 분석 실패 ({news_url}): {e}")
        return {
            "summary": f"[분석 실패] {news_url}",
            "judgment": "중립", "strength": "약", "reasoning": f"오류: {e}",
        }


# ─────────────────────────────────────────────────────────────────────────
# 뉴지(newzy) 풍부 스키마 — 100m1s interpreted/stock-{date}.json news[] 역설계 재현.
#   (생성기 build_daily.py 는 대표 비공개 리포라 출력 2,546건에서 스키마 복원)
#   필드: causal_chain, macro_event, article_type, newzy 5차원(0~1), newzy_score(=5평균),
#         newzy_verdict.  newzy_score 는 코드에서 평균 계산(데이터상 오차 0).
# ─────────────────────────────────────────────────────────────────────────

_NEWZY_DIMS = ("freshness", "persistence", "magnitude", "virality", "tradability")


def _clip01(v) -> float:
    try:
        return max(0.0, min(1.0, round(float(v), 2)))
    except (TypeError, ValueError):
        return 0.0


def analyze_news_newzy(news_url: str, stock_name: str = "", title: str = "") -> dict:
    """뉴스 → 뉴지 스키마 dict. (100m1s newzy 역설계)

    반환: {causal_chain, macro_event, article_type,
           newzy_freshness/persistence/magnitude/virality/tradability,
           newzy_score, newzy_verdict}
    """
    if not GEMINI_API_KEY:
        return {"causal_chain": f"[mock] {title}", "macro_event": "", "article_type": "중립",
                **{f"newzy_{d}": 0.0 for d in _NEWZY_DIMS}, "newzy_score": 0.0,
                "newzy_verdict": "API 키 없음"}
    try:
        req = urllib.request.Request(news_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            news_text = html_to_text(resp.read().decode("utf-8", errors="ignore"))[:3000]

        prompt = f"""당신은 한국 주식 단타/스윙 트레이딩 관점의 뉴스 분석가입니다.
종목: {stock_name}
제목: {title}
URL: {news_url}
본문(일부): {news_text}

이 뉴스가 해당 종목 주가에 미치는 영향을 분석해 아래 JSON 으로만 답하세요.

- causal_chain: 인과사슬을 "원인 → 메커니즘 → 종목 실적/주가 영향" 형태의 화살표(→) 체인 한 단락으로.
- macro_event: 이 재료를 관통하는 거시/테마 맥락 한 줄 (없으면 "").
- article_type: "호재" | "악재" | "시세정형"(단순 등락/특징주) | "공시" | "사건사고" 중 하나.
- 아래 5개 차원을 각각 0.0~1.0 으로 평가:
  · freshness: 정보의 신선도 (신규 사실=높음, 기존 반복/지연=낮음)
  · persistence: 영향 지속성 (단발성=낮음, 구조적·장기=높음)
  · magnitude: 실적/주가 영향 강도 (소폭=낮음, 대형=높음)
  · virality: 시장 관심·확산성 (조용=낮음, 화제·다수보도=높음)
  · tradability: 매매 실행가능성 (실체 있는 재료=높음, 단순 시세/추측=0)
- newzy_verdict: 제목만으로 한 추론이 본문과 일치하는지 자가검증 ("동의: ..." | "반대: ...").

형식:
{{"causal_chain":"...","macro_event":"...","article_type":"호재","freshness":0.0,"persistence":0.0,"magnitude":0.0,"virality":0.0,"tradability":0.0,"newzy_verdict":"..."}}"""

        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
        }).encode("utf-8")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        p = json.loads(result["candidates"][0]["content"]["parts"][0]["text"])

        dims = {f"newzy_{d}": _clip01(p.get(d)) for d in _NEWZY_DIMS}
        score = round(sum(dims.values()) / len(_NEWZY_DIMS), 2)  # 5차원 단순평균 (데이터상 공식)
        at = p.get("article_type", "")
        if at not in ("호재", "악재", "시세정형", "공시", "사건사고"):
            at = "시세정형"
        return {
            "causal_chain": p.get("causal_chain", ""),
            "macro_event": p.get("macro_event", ""),
            "article_type": at,
            **dims,
            "newzy_score": score,
            "newzy_verdict": p.get("newzy_verdict", ""),
        }
    except Exception as e:
        logger.warning(f"newzy 분석 실패 ({news_url}): {e}")
        return {"causal_chain": f"[분석 실패] {news_url}", "macro_event": "", "article_type": "시세정형",
                **{f"newzy_{d}": 0.0 for d in _NEWZY_DIMS}, "newzy_score": 0.0,
                "newzy_verdict": f"오류: {e}"}
