#!/usr/bin/env python3
"""KR 종목 OG 이미지 생성기 — 1200×630 카드 (Pillow).

100m1s og/news/stock/{date}/{code}.png 역설계 재현. 생성기(generate_stock_og.py)는
대표 비공개 news_pipeline 이라, 출력 PNG 디자인을 보고 Pillow 로 재현.

카드 구성: 종목명(골드 밑줄) · 현재가 · 등락률 pill(상승 빨강/하락 파랑)
          + 캔들차트(좌) · 종가 라인차트(우) + 날짜(좌하단).
데이터: kiwoom/{date}.json(랭킹·헤더) + dailybars/{code}.json(차트).

사용:
  cd backend && python -m scripts.kr_og_build [--date YYYY-MM-DD] [--limit N] [--code CODE]
서버 cron: 랭킹/일봉 생성 후. 예) 40 16 * * 1-5 python3 -m scripts.kr_og_build
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
KR_NEWS = REPO_ROOT / "frontend" / "public" / "kr-news"
KIWOOM_DIR = KR_NEWS / "data" / "kiwoom"
DAILYBARS_DIR = KR_NEWS / "data" / "dailybars"
OG_DIR = KR_NEWS / "og" / "news" / "stock"

KST = timezone(timedelta(hours=9))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S")
logger = logging.getLogger("kr_og_build")

# 색상
BG = (238, 240, 245)
CARD = (255, 255, 255)
ACCENT = (26, 43, 74)
TITLE = (33, 37, 52)
GOLD = (224, 176, 67)
GRAY = (90, 96, 110)
DATEC = (150, 156, 168)
PANEL = (242, 243, 247)
UP = (229, 57, 53)     # 상승 빨강
DOWN = (30, 136, 229)  # 하락 파랑
LINE = (150, 160, 182)

_FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
]
_FONT_PATH = next((p for p in _FONT_CANDIDATES if Path(p).exists()), None)


def font(size: int):
    if _FONT_PATH:
        try:
            return ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _load(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _text_bold(draw, xy, text, fnt, fill):
    """faux-bold: 1px 오프셋 덧그리기."""
    x, y = xy
    for dx, dy in ((0, 0), (1, 0), (0, 1)):
        draw.text((x + dx, y + dy), text, font=fnt, fill=fill)


def _candles(draw, rows, box):
    """캔들차트. box=(x0,y0,x1,y1). rows: 최근 N일 [{o,h,l,c}]."""
    x0, y0, x1, y1 = box
    if not rows:
        return
    his = [r["h"] for r in rows]; los = [r["l"] for r in rows]
    hi, lo = max(his), min(los)
    rng = (hi - lo) or 1
    pad = 18
    n = len(rows)
    slot = (x1 - x0 - 2 * pad) / n
    bw = max(3, slot * 0.55)

    def py(v):
        return y1 - pad - (v - lo) / rng * (y1 - y0 - 2 * pad)

    for i, r in enumerate(rows):
        cx = x0 + pad + slot * (i + 0.5)
        up = r["c"] >= r["o"]
        col = UP if up else DOWN
        draw.line([(cx, py(r["h"])), (cx, py(r["l"]))], fill=col, width=2)
        top, bot = py(max(r["o"], r["c"])), py(min(r["o"], r["c"]))
        if bot - top < 1:
            bot = top + 1
        draw.rectangle([cx - bw / 2, top, cx + bw / 2, bot], fill=col)


def _line(draw, rows, box):
    """종가 라인차트 + 평균 점선."""
    x0, y0, x1, y1 = box
    cs = [r["c"] for r in rows]
    if len(cs) < 2:
        return
    hi, lo = max(cs), min(cs)
    rng = (hi - lo) or 1
    pad = 18
    n = len(cs)

    def px(i):
        return x0 + pad + (x1 - x0 - 2 * pad) * i / (n - 1)

    def py(v):
        return y1 - pad - (v - lo) / rng * (y1 - y0 - 2 * pad)

    pts = [(px(i), py(v)) for i, v in enumerate(cs)]
    draw.line(pts, fill=LINE, width=3, joint="curve")
    # 평균 점선
    avg = sum(cs) / n
    ay = py(avg)
    x = x0 + pad
    while x < x1 - pad:
        draw.line([(x, ay), (min(x + 10, x1 - pad), ay)], fill=(170, 178, 196), width=1)
        x += 18


def _rounded_panel(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render(stock: dict, rows: list, date: str, out: Path) -> None:
    """단일 종목 OG 카드 렌더 → PNG 저장."""
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # 카드
    m = 36
    _rounded_panel(d, (m, m, W - m, H - m), 28, CARD)
    inx, iny = 88, 96

    name = stock.get("name", "")
    price = stock.get("price") or 0
    chg = stock.get("change_pct") or 0.0
    col = UP if chg >= 0 else DOWN

    # 종목명 + accent bar + 골드 밑줄
    d.rectangle((inx - 22, iny + 6, inx - 14, iny + 60), fill=ACCENT)
    f_title = font(54)
    _text_bold(d, (inx, iny), name, f_title, TITLE)
    tw = d.textlength(name, font=f_title)
    d.rectangle((inx, iny + 66, inx + min(tw, 230), iny + 71), fill=GOLD)

    # 현재가 + 등락률 pill (우측)
    f_price = font(40)
    price_s = f"{price:,}원"
    pw = d.textlength(price_s, font=f_price)
    pill_s = f"{'+' if chg >= 0 else ''}{chg:.2f}%"
    f_pill = font(30)
    pill_w = d.textlength(pill_s, font=f_pill)
    pill_x1 = W - inx
    pill_x0 = pill_x1 - pill_w - 40
    d.text((pill_x0 - 30 - pw, iny + 6), price_s, font=f_price, fill=GRAY)
    _rounded_panel(d, (pill_x0, iny + 2, pill_x1, iny + 52), 25,
                   (253, 234, 234) if chg >= 0 else (232, 242, 253))
    d.text((pill_x0 + 20, iny + 10), pill_s, font=f_pill, fill=col)

    # 차트 패널 2개
    py0, py1 = 210, 500
    lp = (inx, py0, 580, py1)
    rp = (620, py0, W - inx, py1)
    _rounded_panel(d, lp, 16, PANEL)
    _rounded_panel(d, rp, 16, PANEL)
    if rows:
        _candles(d, rows[-22:], lp)
        _line(d, rows[-60:], rp)

    # 날짜
    d.text((inx, H - m - 64), date, font=font(28), fill=DATEC)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", default=datetime.now(KST).strftime("%Y-%m-%d"))
    ap.add_argument("--limit", type=int, default=0, help="처리 종목 수 (0=전체)")
    ap.add_argument("--code", default="", help="특정 종목코드 1개만")
    args = ap.parse_args()

    if not _FONT_PATH:
        logger.warning("한글 TTF 폰트 미발견 — 텍스트 깨질 수 있음 (NanumGothic 설치 권장)")

    kf = _load(KIWOOM_DIR / f"{args.date}.json")
    ranked = kf.get("daily_top") or kf.get("latest_stocks") or []
    if not ranked:
        logger.error(f"랭킹 파일 없음/비어있음: kiwoom/{args.date}.json")
        return 1
    if args.code:
        ranked = [r for r in ranked if str(r.get("ticker")) == args.code]
    if args.limit > 0:
        ranked = ranked[: args.limit]

    out_dir = OG_DIR / args.date
    done = 0
    for rk in ranked:
        code = str(rk.get("ticker", ""))
        if not code:
            continue
        db = _load(DAILYBARS_DIR / f"{code}.json")
        rows = db.get("rows") or []
        # 헤더용 price/change: dailybars 당일 우선, 없으면 랭킹값
        price = rk.get("last_price") or rk.get("price") or 0
        chg = rk.get("max_change_pct")
        for i, r in enumerate(rows):
            if r["d"] == args.date:
                price = r["c"]
                if i > 0 and rows[i - 1]["c"]:
                    chg = round((r["c"] - rows[i - 1]["c"]) / rows[i - 1]["c"] * 100, 2)
                break
        stock = {"name": rk.get("name", ""), "price": price, "change_pct": chg or 0.0}
        render(stock, rows, args.date, out_dir / f"{code}.png")
        done += 1
        logger.info(f"  og {code} {stock['name']} → {len(rows)}일 차트")

    logger.info(f"✓ {args.date} OG {done}장 생성 → {out_dir}")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
