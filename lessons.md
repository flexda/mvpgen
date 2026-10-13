# 이전 실행에서 critic이 지적한 문제

- [build] 실행 예시 `PORT=8000 uv run uvicorn ... --port $PORT`에서 $PORT는 같은 줄의 PORT=8000 할당보다 먼저 셸이 펼친다. 그래서 PORT가 미리 설정돼 있지 않으면 `--port` 뒤에 값이 비어 uvicorn이 실패한다. -> `export PORT=8000` 다음 줄에 실행 명령을 쓰거나, `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`처럼 포트를 직접 적는다.
