# lecture — 주식 강의 페이지 (MD → HTML)

`lecture.md`(콘텐츠 단일 소스)를 편집하고 `build.py`를 돌리면 `lecture.html`이 생성됩니다.
디자인/레이아웃은 `template.html`에 있으니 콘텐츠 수정은 **`lecture.md`만** 건드리면 됩니다.

## 구성

| 파일 | 역할 |
|------|------|
| `lecture.md` | **콘텐츠 소스** (프론트매터 + 10챕터). 여기만 편집 |
| `template.html` | 디자인 셸 (CSS·헤더·푸터). `{{TITLE}}`/`{{DESCRIPTION}}`/`{{ROBOTS}}`/`{{CONTENT}}` 치환 |
| `README.md` | 이 문서 |

> 빌더는 **공유** `frontend/build.py` 하나를 씁니다 (폴더별 build.py 없음).
> 프론트매터에 `layout: lecture` 가 있어야 챕터/목차 레이아웃으로 빌드됩니다.

## 사용

```bash
cd ..                    # frontend/
python3 build.py         # 모든 폴더(lecture, terms, …) 빌드
python3 build.py lecture # 이 폴더만 빌드 → frontend/lecture.html
```

의존성: Python 3 (표준 라이브러리만, 외부 패키지 불필요).

## 편집 컨벤션 (lecture.md)

| 마크업 | 결과 |
|--------|------|
| `# NN \| 레벨 \| 제목` | 챕터 (레벨: 기초/중급/실전/정리 → `Chapter NN — 레벨`) |
| `## 소제목` | h3 소제목 |
| `> 인용` (연속 줄) | 인용 박스 `.quote` (여러 줄은 `<br>`로 합침) |
| `> — 부연` | 인용 하단 부연 `.quote-attr` |
| `:::keypoint 제목` … `:::` | 핵심 박스 `.keypoint` |
| `:::warning` … `:::` | 경고 박스 `.warning` |
| `- [ ] 항목` | 체크리스트 `.checklist` |
| `- 항목` / `1. 항목` | 일반 목록 ul/ol |
| `\| a \| b \|` | 표 (1행=헤더, 2행=구분선) |
| `**굵게**` | `<strong>` |
| `[[강조]]` (headline/footer) | 골드 강조 |

- **목차(TOC)** 는 챕터에서 자동 생성. 구분선 위치는 `build.py`의 `TOC_DIVIDERS_BEFORE`.
- 프론트매터 키: `title`, `robots`, `eyebrow`, `headline`, `description`, `footer`(여러 줄 `|`).

## 검증

원본 `lecture.html` ↔ 생성본: 챕터 10 / h3 25 / quote 19 / keypoint 6 / warning 4 / table 4 /
checklist 4 / TOC 12 **전부 일치**, 가시 텍스트 100% 동일 (라운드트립 무손실).
