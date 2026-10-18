# 이전 실행에서 critic이 지적한 문제

- [build] 실행 예시 `PORT=8000 uv run uvicorn ... --port $PORT`에서 $PORT는 같은 줄의 PORT=8000 할당보다 먼저 셸이 펼친다. 그래서 PORT가 미리 설정돼 있지 않으면 `--port` 뒤에 값이 비어 uvicorn이 실패한다. -> `export PORT=8000` 다음 줄에 실행 명령을 쓰거나, `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`처럼 포트를 직접 적는다.
- [plan] F6 수집 현황 페이지(/sources)는 운영자가 수집 실패, manual 갤러리, 점검일을 확인하는 관리용 화면이다. 원래 아이디어('오늘 볼 만한 전시 추천')를 시연하는 데 필요하지 않다. intent에도 연결되어 있지 않다(F5, F6 모두 intent의 feature_ids에 없음). 루브릭 2의 '관리자 화면처럼 시연에 필요 없는 기능'에 해당한다. MMCA 동기화 버튼이 이 페이지에만 있어서, 핵심 경로(F2)가 보조 화면에 묶여 있다. -> F6을 빼거나 축소한다. 'MMCA 동기화' 버튼과 마지막 동기화 시각만 홈(/) 하단으로 옮기고, 갤러리 19곳 표와 수집 실패 목록은 out of scope로 돌린다. 남기려면 intent와 연결되는 이유를 명시한다.
