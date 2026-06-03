#!/usr/bin/env python3
"""MD → HTML 정적 페이지 빌더 (폴더 중심, 다중 빌드).

각 하위 폴더에 콘텐츠 소스 `*.md`(README.md 제외) + `template.html` 를 두면,
이 스크립트가 폴더별로 `<이름>.html` 을 frontend/ 아래에 생성한다.

  frontend/
    build.py            ← 이 파일 (공유)
    lecture/  lecture.md + template.html   → frontend/lecture.html
    terms/    terms.md   + template.html   → frontend/terms.html
    <새폴더>/ <name>.md  + template.html   → frontend/<name>.html

레이아웃(프론트매터 `layout`):
  - lecture : 챕터(`# NN | 레벨 | 제목`) + 자동 목차 + page-header + 푸터노트
  - doc     : 약관/문서형 (h1 heading + meta + `## 제목` 섹션). 기본값.

공통 블록(두 레이아웃 모두): `## 소제목`, `> 인용`(`> — 부연`),
  `:::keypoint 제목 … :::`, `:::warning … :::`, `:::notice … :::`,
  `- [ ] 체크`, `- 불릿` / `1. 번호`, `| 표 |`, `**굵게**`.

사용:
  python3 build.py            # 모든 폴더 빌드
  python3 build.py lecture    # 특정 폴더만 (여러 개 나열 가능)
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent  # frontend/


# ── 인라인/이스케이프 ─────────────────────────────────────
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(s))


def accent_headline(s: str) -> str:
    return re.sub(r"\[\[(.+?)\]\]", r'<span class="accent">\1</span>', esc(s))


def accent_footer(s: str) -> str:
    s = esc(s).replace("\n", "<br>\n    ")
    return re.sub(r"\[\[(.+?)\]\]",
                  r'<span style="color: var(--am); font-weight: 700;">\1</span>', s)


# ── 프론트매터 ───────────────────────────────────────────
def parse_frontmatter(text: str):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta, lines, i = {}, m.group(1).split("\n"), 0
    while i < len(lines):
        km = re.match(r"^(\w+):\s*(.*)$", lines[i])
        if km:
            key, val = km.group(1), km.group(2).strip()
            if val == "|":  # 여러 줄 블록
                block, i = [], i + 1
                while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                    block.append(lines[i][2:] if lines[i].startswith("  ") else "")
                    i += 1
                meta[key] = "\n".join(block).rstrip()
                continue
            meta[key] = val
        i += 1
    return meta, text[m.end():]


# ── 블록 렌더러 (공통) ────────────────────────────────────
def render_blocks(lines: list[str], sub_tag: str = "h2") -> list[str]:
    out, i, n = [], 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s.startswith("## "):
            out.append(f"  <{sub_tag}>{inline(s[3:].strip())}</{sub_tag}>")
            i += 1
        elif s.startswith(":::keypoint"):
            title = s[len(":::keypoint"):].strip()
            buf, i = [], i + 1
            while i < n and lines[i].strip() != ":::":
                buf.append(lines[i].strip()); i += 1
            i += 1
            out.append('  <div class="keypoint">')
            out.append(f'    <div class="keypoint-title">{esc(title)}</div>')
            out.append(f'    <p>{inline(" ".join(x for x in buf if x))}</p>')
            out.append("  </div>")
        elif s.startswith(":::warning") or s.startswith(":::notice"):
            cls = "warning" if s.startswith(":::warning") else "notice"
            buf, i = [], i + 1
            while i < n and lines[i].strip() != ":::":
                buf.append(lines[i].strip()); i += 1
            i += 1
            out.append(f'  <div class="{cls}">{inline(" ".join(x for x in buf if x))}</div>')
        elif s.startswith(">"):
            main, attr = [], []
            while i < n and lines[i].strip().startswith(">"):
                q = lines[i].strip()[1:].strip()
                (attr if q.startswith("— ") or q.startswith("- ") else main).append(
                    q[2:].strip() if q.startswith("— ") or q.startswith("- ") else q)
                i += 1
            html = '  <div class="quote">' + "<br>".join(inline(x) for x in main)
            if attr:
                html += f'<div class="quote-attr">{inline(" ".join(attr))}</div>'
            out.append(html + "</div>")
        elif re.match(r"^- \[[ x]\]", s):
            items = []
            while i < n and re.match(r"^- \[[ x]\]", lines[i].strip()):
                items.append(lines[i].strip()[5:].strip()); i += 1
            out.append('  <ul class="checklist">')
            out += [f'    <li><span class="check-icon">&#9632;</span>{inline(it)}</li>' for it in items]
            out.append("  </ul>")
        elif re.match(r"^\d+\.\s", s):
            items = []
            while i < n and re.match(r"^\d+\.\s", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s", "", lines[i].strip())); i += 1
            out.append("  <ol>")
            out += [f"    <li>{inline(it)}</li>" for it in items]
            out.append("  </ol>")
        elif s.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- ") and not re.match(r"^- \[", lines[i].strip()):
                items.append(lines[i].strip()[2:].strip()); i += 1
            out.append("  <ul>")
            out += [f"    <li>{inline(it)}</li>" for it in items]
            out.append("  </ul>")
        elif s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            if len(rows) >= 2:
                out.append("  <table>")
                out.append("    <thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr></thead>")
                out.append("    <tbody>")
                out += ["      <tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[2:]]
                out.append("    </tbody>")
                out.append("  </table>")
        else:
            para = []
            while i < n and lines[i].strip() and not re.match(r"^(#|>|-|\d+\.|\||:::)", lines[i].strip()):
                para.append(lines[i].strip()); i += 1
            out.append(f"  <p>{inline(' '.join(para))}</p>")
    return out


# ── 레이아웃별 콘텐츠 생성 ────────────────────────────────
def build_lecture(meta: dict, body: str) -> str:
    dividers = set(x.strip() for x in meta.get("toc_dividers", "04,07").split(",") if x.strip())
    chapters = []
    for p in re.split(r"(?m)^#\s+", body):
        p = p.strip()
        if not p:
            continue
        head, *rest = p.split("\n")
        hm = re.match(r"^(\d+)\s*\|\s*(\S+)\s*\|\s*(.+)$", head.strip())
        if not hm:
            continue
        chapters.append({"num": hm.group(1), "level": hm.group(2), "title": hm.group(3).strip(),
                         "blocks": render_blocks(rest, "h3")})
    header = [
        '<div class="page-header">',
        f'  <div class="page-eyebrow">{esc(meta.get("eyebrow",""))}</div>',
        f'  <h1 class="page-title">{accent_headline(meta.get("headline",""))}</h1>',
        f'  <p class="page-desc">{esc(meta.get("description",""))}</p>',
        "</div>", "",
    ]
    toc = ['<div class="toc">', '  <div class="toc-title">목차</div>', '  <ol class="toc-list">']
    for ch in chapters:
        if ch["num"] in dividers:
            toc.append('    <li class="toc-divider"></li>')
        toc.append(f'    <li><a href="#ch{int(ch["num"])}"><span class="toc-num">{ch["num"]}</span>{esc(ch["title"])}</a></li>')
    toc += ["  </ol>", "</div>", ""]
    secs = []
    for ch in chapters:
        secs.append(f'<section class="chapter" id="ch{int(ch["num"])}">')
        secs.append(f'  <div class="chapter-label">Chapter {ch["num"]} — {ch["level"]}</div>')
        secs.append(f'  <h2>{inline(ch["title"])}</h2>')
        secs.append("\n".join(ch["blocks"]))
        secs.append("</section>")
    foot = []
    if meta.get("footer"):
        foot = ['', '<div class="section-divider"></div>',
                '<div style="text-align:center; padding: 24px 0;">',
                '  <p style="font-size: 13px; color: var(--dm); line-height: 1.7;">',
                f'    {accent_footer(meta["footer"])}', "  </p>", "</div>"]
    return "\n".join(header + toc + secs + foot)


def build_doc(meta: dict, body: str) -> str:
    out = [f'  <h1>{esc(meta.get("heading",""))}</h1>']
    if meta.get("meta"):
        out.append(f'  <div class="meta">{esc(meta["meta"])}</div>')
    out += render_blocks(body.split("\n"), "h2")
    return "\n".join(out)


# ── 폴더 1개 빌드 ─────────────────────────────────────────
def build_folder(folder: Path) -> Path | None:
    tpl_path = folder / "template.html"
    mds = [p for p in folder.glob("*.md") if p.name.lower() != "readme.md"]
    if not tpl_path.exists() or not mds:
        return None
    md = mds[0]
    raw = re.sub(r"<!--.*?-->", "", md.read_text(encoding="utf-8"), flags=re.S)
    meta, body = parse_frontmatter(raw)
    layout = meta.get("layout", "doc")
    content = build_lecture(meta, body) if layout == "lecture" else build_doc(meta, body)

    html = tpl_path.read_text(encoding="utf-8")
    for k, v in {
        "TITLE": meta.get("title", ""), "DESCRIPTION": meta.get("description", ""),
        "ROBOTS": meta.get("robots", "index,follow"),
        "OG_URL": meta.get("og_url", ""), "OG_IMAGE": meta.get("og_image", ""),
    }.items():
        html = html.replace("{{" + k + "}}", esc(v))
    html = html.replace("{{CONTENT}}", content)

    # Vite 가 서빙하는 public/ 로 출력 (→ /lecture.html, /terms.html 로 접근)
    out_dir = BASE / "public"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{md.stem}.html"
    out.write_text(html, encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    targets = argv or [d.name for d in sorted(BASE.iterdir())
                       if d.is_dir() and (d / "template.html").exists()]
    if not targets:
        print("빌드할 폴더 없음 (template.html + *.md 를 가진 하위 폴더 필요)")
        return 1
    built = 0
    for name in targets:
        folder = BASE / name
        if not folder.is_dir():
            print(f"⚠️  폴더 없음: {name}")
            continue
        out = build_folder(folder)
        if out:
            print(f"✓ {name}/ → {out.relative_to(BASE)}")
            built += 1
        else:
            print(f"⚠️  건너뜀: {name} (template.html + *.md 필요)")
    print(f"완료: {built}개 빌드")
    return 0 if built else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
