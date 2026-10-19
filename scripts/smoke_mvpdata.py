"""mvpdata의 실제 DB 경로(Supabase CLI db push, pooler 접속, 행 수, 읽기 전용 검사, 가리기)를 LLM 없이 확인한다.

빈 프로젝트에서만 돈다(사전 점검 통과가 조건). 끝나면 이 스크립트가 만든 스키마(raw, core)와 적용 기록 한 줄을 지운다.

    uv run python scripts/smoke_mvpdata.py --secrets /Users/reflectdata/Project/loop-2-test/secrets <작업 폴더>
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from mvpgen.dataspec import DataSpec
from mvpgen.dbverify import DbVerifier, PgDatabase, url_secrets
from mvpgen.envfiles import load_supabase_url

VERSION = "20000101000000"
MIGRATION = """\
create schema if not exists raw;
create schema if not exists core;
create table raw.smoke_pages (page int primary key, payload text not null);
create table core.smoke_item (id int primary key, title text not null);
"""
INGEST = """\
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None) as conn:
    conn.execute("insert into raw.smoke_pages values (1, 'p') on conflict do nothing")
    conn.execute("insert into core.smoke_item values (1, 'a'), (2, 'b') on conflict do nothing")
print("pages", os.environ["INGEST_MAX_PAGES"])
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path, help="가짜 앱을 만들 빈 폴더")
    ap.add_argument("--secrets", type=Path, default=Path("secrets"))
    ap.add_argument("--supabase-bin", default="supabase")
    ap.add_argument("--keep", action="store_true", help="확인 뒤 스키마와 기록을 지우지 않는다")
    args = ap.parse_args()

    url = load_supabase_url(args.secrets.resolve())
    bin_path = shutil.which(args.supabase_bin)
    if not url or not bin_path:
        print("SUPABASE_DB_URL 또는 Supabase CLI가 없다", file=sys.stderr)
        return 2
    run_dir = args.workdir.resolve()
    app = run_dir / "app"
    (app / "supabase" / "migrations").mkdir(parents=True, exist_ok=False)
    (app / "supabase" / "migrations" / f"{VERSION}_smoke.sql").write_text(MIGRATION)
    (app / "ingest.py").write_text(INGEST)

    db = PgDatabase(url)
    verifier = DbVerifier(db_url=url, supabase_bin=bin_path, db=db)
    problems = verifier.preflight(run_dir)
    if problems:
        print("사전 점검 실패:\n" + "\n".join(problems), file=sys.stderr)
        return 2

    spec = DataSpec.model_validate({
        "name": "smoke", "summary": "DB 경로 확인",
        "source": {"name": "없음", "endpoint": "-", "key_env": None, "doc": "-"},
        "intent": [{"requirement": "적재", "covered_by": ["core.smoke_item"]}],
        "tables": [{"name": "raw.smoke_pages", "description": "p"}, {"name": "core.smoke_item", "description": "i"}],
        "checks": [{"id": "positive_id", "description": "id는 양수", "sql": "select * from core.smoke_item where id <= 0"}],
        "test_cmd": "true", "ingest_cmd": f"{sys.executable} ingest.py",
    })
    try:
        result = verifier.verify(app, spec, run_dir, "smoke", 1)
        print(result.report())
        print(f"\n근거: {run_dir / 'db' / 'smoke.md'}")
        leaked = [s for s in url_secrets(url) if s in (run_dir / "db" / "smoke.md").read_text()]
        print("가리기: " + ("실패, 근거 파일에 비밀값이 있다" if leaked else "통과"))
        return 0 if result.ok and not leaked else 1
    finally:
        if not args.keep:
            with db._connect() as conn:
                conn.execute("drop schema if exists raw, core cascade")
                if conn.execute("select to_regclass('supabase_migrations.schema_migrations')").fetchone()[0]:
                    conn.execute("delete from supabase_migrations.schema_migrations where version = %s", (VERSION,))
            print("정리: raw, core 스키마와 적용 기록을 지웠다")


if __name__ == "__main__":
    raise SystemExit(main())
