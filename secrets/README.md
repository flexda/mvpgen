# secrets

API 키를 두는 폴더. `claude.env`와 `mvp.env`는 `.gitignore`로 제외되고, 권한은 본인만 읽을 수 있게(600) 설정되어 있다.

| 파일 | 용도 | 누가 쓰나 |
| --- | --- | --- |
| `claude.env` | `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` 등 Claude 호출용 인증. 구독 로그인을 쓰면 비워 둔다 | mvpgen 자신 |
| `mvp.env` | 생성될 MVP가 쓸 외부 API 키 | Build 세션, 생성된 앱의 테스트와 실행 |

- `*.example`은 형식 예시다. 실제 값은 넣지 않는다.
- 셸에 이미 export된 값이 `claude.env`보다 우선한다.
- 생성된 앱을 실행할 때는 mvpgen의 Claude 키를 환경에서 빼고 `mvp.env` 값만 더한다.
- 에이전트는 이 폴더를 읽을 수 없고, 키 값을 코드나 파일, 명령에 직접 쓰면 차단된다.
- 다른 위치를 쓰려면 `uv run mvpgen ... --secrets <폴더>`.
