# 국립현대미술관 전시정보 API

- 출처: 문화데이터광장
- 문서: https://www.culture.go.kr/data/openapi/openapiView.do?id=44
- 엔드포인트: `https://api.kcisa.kr/openapi/service/rest/moca/docMeta`
- 인증: serviceKey 필수 
- 서비스키: 환경변수 `MMCA_SERVICE_KEY`로 읽는다
- 응답 형식: XML (JSON 가능)

## 파라미터

| 파라미터 | 필수 | 설명 |
|---|---|---|
| serviceKey | 필수 | 서비스 인증키 |
| numOfRows | 선택 | 페이지당 레코드 수 |
| pageNo | 선택 | 페이지 번호 |

## 응답 필드

| 필드 | 설명 |
|---|---|
| title | 전시명 |
| eventPeriod | 전시 기간 |
| venue | 장소 |
| creator | 주최자 |
| publisher | 발행기관 |
| charge | 요금 |
| subjectCategory | 주제 분류 |
| subDescription | 보조 설명 |
| person | 참여자 |
| rights | 저작권 |
| collectionDb | 소속 DB |
