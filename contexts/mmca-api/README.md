# mmca-api

`mvpdata` 첫 실험용 자료. 국립현대미술관 전시정보 API 문서만 둔다.

- `mmca-exhibition-api.md`: 엔드포인트, 파라미터, 응답 필드. `contexts/today-exhibitions/`에서 복사했다.
- 키는 `secrets/mvp.env`의 `MMCA_SERVICE_KEY`로 넘긴다. 이 폴더에는 값을 넣지 않는다.

2026-10-13 수집으로 확인한 사실 (출처: docs/mmca-pipeline-2026-10-13/index.html):

- 날짜 필터 파라미터가 없다. serviceKey, numOfRows, pageNo만 받는다.
- 전체는 약 3980건이다. 모두 받은 뒤 거른다.
- 같은 전시가 표기만 바꿔 여러 번 나오고, 값에 `<br/>` 같은 HTML 태그가 섞여 있으며, 제목이 "테스트"인 레코드가 있다.
- subjectCategory(과거, 현재, 예정)는 실제 기간과 맞지 않는다. 기간은 eventPeriod로 계산한다.
