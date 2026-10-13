# docs/ 파일 설명

서울 주요 갤러리와 국립현대미술관의 전시정보를 수집·정리하기 위한 스크립트, 설정, 레퍼런스 파일 모음이다.

---

## 📂 파일 한눈에 보기

| 파일명 | 역할 및 성격 | 핵심 내용 & 특징 |
|---|---|---|
| [`galleries.json`](galleries.json) | 갤러리 메타데이터/설정 | 19개 갤러리 화이트리스트 및 사이트별 예외(EUC-KR, JS렌더링, 지점 필터 등) 정의 |
| [`crawl_galleries.py`](crawl_galleries.py) | 상업 화랑 크롤러 | Requests + Claude Haiku 기반 주간 서울 전시 추출 스크립트 |
| [`list_exhibition_venues.py`](list_exhibition_venues.py) | 서울시 공공 API 수집기 | `culturalEventInfo` API 기반 전시/미술 장소 집계 및 기관 분류 |
| [`mmca-exhibition-api.md`](mmca-exhibition-api.md) | 국현(MMCA) API 레퍼런스 | 문화데이터광장 오픈API 엔드포인트 및 인증키 명세 |
| [`sample_exhibitions_2026-10-06.csv`](sample_exhibitions_2026-10-06.csv) | 수집 데이터 샘플 (22건) | 출력 스키마 확인 및 실패/검증 사유(`needs_review`) 샘플 |

---

## 상세 파일 설명

### galleries.json
갤러리 화이트리스트 설정 파일. `crawl_galleries.py`가 읽는 수집 대상 목록이다.

- 갤러리별로 `id`, `name`, `list_url`, `platform`, `robots`, `sitemap`, `seoul_label`, `status`, `note`를 정의한다.
- `status` 값:
  - `ok` - 자동 수집 가능
  - `check` - URL 또는 HTML 구조 재확인 필요
  - `manual` - 자동 수집 보류 (JS 렌더링, 도메인 이전 등)
- 수집 대상: 국제갤러리, 갤러리현대, PKM, 아라리오, 타데우스 로팍, 갤러리바톤, 에스더 쉬퍼, 페이스, 화이트큐브, 페로탕, 리만머핀, 글래드스톤, 탕 컨템포러리, 쾨닉, 리안갤러리, 가나아트, 학고재, P21, 원앤제이갤러리 (총 19곳)

---

### crawl_galleries.py
`galleries.json`의 갤러리 목록을 순회하며 현재 서울 전시 정보를 수집하는 메인 스크립트다.

**동작 흐름:**
1. `robots.txt` 확인 - 차단된 URL은 요청하지 않는다.
2. `polite_get()` - 도메인당 10초 간격으로 요청한다.
3. HTML에서 불필요한 태그(script, style 등)를 제거하고 텍스트만 추출한다.
4. Claude Haiku(`claude-haiku-4-5-20251001`)에 텍스트를 넘겨 전시 정보를 JSON으로 추출한다.
5. 추출 결과를 검증(제목 존재, 종료일, 기간 역전 등)하고 중복을 제거한다.
6. `out/exhibitions_YYYY-MM-DD.csv`로 저장하고 이전 실행 대비 신규 전시를 표시한다.

**실행 옵션:**
```
python crawl_galleries.py              # 전체 수집
python crawl_galleries.py --audit     # robots/sitemap 점검만
python crawl_galleries.py --only kukje,pkm  # 특정 갤러리만
```

**출력 CSV 컬럼:** `gallery_id`, `gallery`, `branch`, `title`, `artists`, `start_date`, `end_date`, `source_url`, `fetched_at`, `needs_review`

**의존성:** `requests`, `beautifulsoup4`, `anthropic`, `ANTHROPIC_API_KEY` 환경변수

---

### list_exhibition_venues.py
서울시 공공 API(`culturalEventInfo`)에서 '전시/미술' 카테고리 행사를 전부 받아 장소별로 집계하는 독립 스크립트다.

- `crawl_galleries.py`와 독립적으로 실행한다.
- 갤러리 이름 키워드로 기관 유형을 분류한다(서울시립미술관, 국립, 공공, 미술관, 갤러리 등).
- 결과를 `venues.csv`로 저장한다. (컬럼: 장소, 기관명, 분류, 행사수, 자치구, 전시명예시)
- **의존성:** `requests`, `SEOUL_API_KEY` 환경변수

---

### mmca-exhibition-api.md
국립현대미술관(MMCA) 전시정보 API 레퍼런스 문서다.

- 출처: 문화데이터광장
- 엔드포인트: `https://api.kcisa.kr/openapi/service/rest/moca/docMeta`
- 인증: `serviceKey` 필수 (환경변수 MMCA_SERVICE_KEY)
- 응답 형식: XML (JSON 가능)
- 주요 응답 필드: `title`, `eventPeriod`, `venue`, `creator`, `publisher`, `charge`, `subjectCategory` 등

---

### sample_exhibitions_2026-10-06.csv
`crawl_galleries.py`의 2026-10-06 실행 결과 샘플이다.

- 수집 성공 14건, 수집 실패 4건(리안갤러리, 가나아트, 쾨닉, 글래드스톤)
- `needs_review` 컬럼에 각 항목의 검증 문제가 기록되어 있다. (시작일 미확인, 참여작가 미표기, 기간 미표기 등)
- 수집 실패 갤러리는 빈 행으로 기록되고 실패 사유가 `needs_review`에 남는다.
