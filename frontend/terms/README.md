# terms — 이용약관 페이지 (MD → HTML)

`terms.md`(콘텐츠 소스)를 편집하고 `build.py`를 돌리면 `terms.html`이 생성됩니다.
디자인은 `template.html`에 있으니 콘텐츠는 **`terms.md`만** 수정하면 됩니다. (lecture 폴더와 동일 방식)

## 구성
| 파일 | 역할 |
|------|------|
| `terms.md` | 콘텐츠 소스 (프론트매터 + 섹션) |
| `template.html` | 디자인 셸 (`{{TITLE}}`/`{{DESCRIPTION}}`/`{{ROBOTS}}`/`{{OG_URL}}`/`{{OG_IMAGE}}`/`{{CONTENT}}`) |

> 빌더는 **공유** `frontend/build.py` 하나를 씁니다. `layout` 미지정 시 기본 `doc`(약관/문서형).

## 사용
```bash
cd ..                  # frontend/
python3 build.py       # 모든 폴더 빌드
python3 build.py terms # 이 폴더만 빌드 → frontend/terms.html
```

## 편집 컨벤션 (terms.md)
| 마크업 | 결과 |
|--------|------|
| `## N. 제목` | h2 섹션 |
| 본문 줄 | p |
| `- 항목` | ul 목록 |
| `:::warning … :::` | 경고 박스(.warning) |
| `:::notice … :::` | 안내 박스(.notice) |
| `**굵게**` | strong |

- 첫 `##` 이전 단락은 intro(머리말).
- 프론트매터: `title`, `description`, `robots`, `og_url`, `og_image`, `heading`(h1), `meta`(날짜 줄).

## 검증
원본 `terms.html` ↔ 생성본: h1 1 / h2 10 / p 9 / ul 4 / li 16 / warning 1 / notice 1 **전부 일치**,
가시 텍스트 100% 동일.
