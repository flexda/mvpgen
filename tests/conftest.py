import json
import sys
from pathlib import Path

import pytest

from mvpgen.prompts import SPEC_EXAMPLE


@pytest.fixture
def spec_dict() -> dict:
    return json.loads(json.dumps(SPEC_EXAMPLE))


@pytest.fixture
def python_server_app(tmp_path: Path) -> Path:
    """PORT 환경변수로 뜨는 작은 HTTP 서버 앱."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "server.py").write_text(
        "import os, http.server\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'Hello MVP')\n"
        "    def log_message(self, *a): pass\n"
        "http.server.HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n"
    )
    return app


PY = sys.executable
