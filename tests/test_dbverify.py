import copy
import json

from mvpgen.data_prompts import DATA_SPEC_EXAMPLE
from mvpgen.dataspec import DataSpec
from mvpgen.dbverify import DbVerifier, check_migrations, load_ledger, mask, url_secrets
from mvpgen.verify import StepResult

URL = "postgresql://postgres.abc:s3cr%40tpw@aws-0.pooler.supabase.com:5432/postgres"
TABLES = ["raw.air_pages", "core.measurement", "mart.station_daily"]


def make_app(tmp_path, files: dict[str, str]):
    app = tmp_path / "app"
    mig = app / "supabase" / "migrations"
    mig.mkdir(parents=True)
    for name, sql in files.items():
        (mig / name).write_text(sql)
    return app


def test_url_secrets_include_decoded_password():
    values = url_secrets(URL)
    assert URL in values and "s3cr%40tpw" in values and "s3cr@tpw" in values
    assert mask(f"error at {URL} pw s3cr@tpw", values) == "error at *** pw ***"


def test_check_migrations_rules(tmp_path):
    app = make_app(tmp_path, {
        "20261019000000_init.sql": "create schema if not exists raw;",
        "20261019000001_more.sql": "create table raw.x (id int);",
    })
    assert check_migrations(app, {}) == []
    assert check_migrations(tmp_path / "none", {})[0].endswith("파일(.sql)이 없다")


def test_locked_file_cannot_change_or_disappear(tmp_path):
    app = make_app(tmp_path, {"20261019000000_init.sql": "create schema if not exists raw;"})
    ledger = {"20261019000000_init.sql": "0" * 64, "20261019000005_gone.sql": "0" * 64}
    problems = check_migrations(app, ledger)
    assert any("init.sql: 이미 DB에 적용한 파일을 고쳤다" in p for p in problems)
    assert any("gone.sql: 이미 DB에 적용한 파일을 지웠다" in p for p in problems)


def test_new_migration_must_be_later_and_safe(tmp_path):
    app = make_app(tmp_path, {
        "20261019000005_init.sql": "create schema raw;",
        "20261019000001_early.sql": "create table raw.y (id int);",
        "20261019000006_bad.sql": "drop schema mart cascade; create schema app; delete from auth.users;",
        "Bad-Name.sql": "select 1;",
    })
    from mvpgen.dbverify import _sha

    ledger = {"20261019000005_init.sql": _sha(app / "supabase/migrations/20261019000005_init.sql")}
    text = "\n".join(check_migrations(app, ledger))
    assert "early.sql: 새 파일의 시각" in text
    assert "DROP SCHEMA" in text and "스키마 app" in text and "(auth)" in text
    assert "Bad-Name.sql: 이름은" in text


class FakeDb:
    def __init__(self, counts, violations=0):
        self.applied: set[str] = set()
        self._counts = list(counts)
        self._violations = violations
        self.existing: set[str] = set()

    def applied_versions(self):
        return set(self.applied)

    def counts(self, tables):
        return dict(zip(tables, self._counts.pop(0)))

    def violations(self, query):
        return self._violations

    def schemas(self, names):
        return set(self.existing)


def make_verifier(db):
    def push(app_dir, env):
        assert "DATABASE_URL" not in env
        for p in (app_dir / "supabase" / "migrations").glob("*.sql"):
            db.applied.add(p.name.split("_", 1)[0])
        return StepResult("db push", True, 0, f"pushed to {URL}", 0.0)

    return DbVerifier(db_url=URL, supabase_bin="supabase", extra_env={"AIR_API_KEY": "k" * 10}, db=db, push=push)


def spec(**over) -> DataSpec:
    s = copy.deepcopy(DATA_SPEC_EXAMPLE)
    # 테스트에는 DB URL이 없어야 하고, 적재에는 URL과 페이지 제한이 넘어가야 한다
    s.update({"install_cmd": None, "test_cmd": 'test -z "$DATABASE_URL"',
              "ingest_cmd": 'test -n "$DATABASE_URL" && test "$INGEST_MAX_PAGES" = 2 && test -n "$AIR_API_KEY"', **over})
    return DataSpec.model_validate(s)


def test_verify_success_locks_and_masks(tmp_path):
    app = make_app(tmp_path, {"20261019000000_init.sql": "create schema if not exists raw;"})
    db = FakeDb([[0, 0, 0], [5, 5, 2], [5, 5, 2]])
    result = make_verifier(db).verify(app, spec(), tmp_path, "check-1", 2)

    assert result.ok, result.report()
    assert [s.name for s in result.steps] == ["migrations", "test", "db push", "tables", "ingest 1", "ingest 2",
                                              "idempotency", "checks"]
    assert list(load_ledger(tmp_path)) == ["20261019000000_init.sql"]
    evidence = (tmp_path / "db" / "check-1.md").read_text() + (tmp_path / "db" / "check-1.json").read_text()
    assert "s3cr" not in evidence and "| core.measurement | 0 | 5 | 5 |" in evidence


def test_verify_fails_when_not_idempotent(tmp_path):
    app = make_app(tmp_path, {"20261019000000_init.sql": "create schema if not exists raw;"})
    db = FakeDb([[0, 0, 0], [5, 5, 2], [5, 10, 2]])
    result = make_verifier(db).verify(app, spec(), tmp_path, "check-1", 2)
    assert not result.ok and result.failed_step.name == "idempotency"
    assert "core.measurement" in result.failed_step.output_tail and "5 -> 10" in result.failed_step.output_tail


def test_verify_fails_on_missing_table_and_check_violation(tmp_path):
    app = make_app(tmp_path, {"20261019000000_init.sql": "create schema if not exists raw;"})
    result = make_verifier(FakeDb([[0, None, 0]])).verify(app, spec(), tmp_path, "c", 2)
    assert result.failed_step.name == "tables"

    db = FakeDb([[0, 0, 0], [5, 5, 2], [5, 5, 2]], violations=3)
    result = make_verifier(db).verify(app, spec(), tmp_path, "c2", 2)
    assert result.failed_step.name == "checks" and "위반 3행" in result.failed_step.output_tail
    assert json.loads((tmp_path / "db" / "c2.json").read_text())["checks"]["daily_unique"] == 3


def test_verify_stops_before_db_when_locked_file_edited(tmp_path):
    app = make_app(tmp_path, {"20261019000000_init.sql": "create schema if not exists raw;"})
    db = FakeDb([[0, 0, 0], [5, 5, 2], [5, 5, 2]])
    v = make_verifier(db)
    assert v.verify(app, spec(), tmp_path, "c1", 2).ok
    (app / "supabase/migrations/20261019000000_init.sql").write_text("create schema if not exists core;")
    result = v.verify(app, spec(), tmp_path, "c2", 2)
    assert [s.name for s in result.steps] == ["migrations"] and "고쳤다" in result.steps[0].output_tail


def test_push_success_without_history_fails_loudly(tmp_path):
    # 적용 기록의 버전 형식이 가정과 다르면 아무것도 잠기지 않는다. 조용히 넘어가지 않아야 한다
    app = make_app(tmp_path, {"20261019000000_init.sql": "create schema if not exists raw;"})
    db = FakeDb([[0, 0, 0]])
    v = make_verifier(db)
    v.push = lambda app_dir, env: StepResult("db push", True, 0, "", 0.0)
    result = v.verify(app, spec(), tmp_path, "c", 2)
    assert result.failed_step.name == "db push" and "적용 기록" in result.failed_step.output_tail
    assert load_ledger(tmp_path) == {}


def test_preflight_fresh_and_resume(tmp_path):
    db = FakeDb([])
    v = make_verifier(db)
    assert v.preflight(tmp_path) == []

    db.applied, db.existing = {"20261019000000"}, {"raw"}
    problems = v.preflight(tmp_path)
    assert len(problems) == 2 and "이전 실행" in problems[0]

    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "ledger.json").write_text(json.dumps({"20261019000000_init.sql": "0" * 64}))
    assert v.preflight(tmp_path) == []
    db.applied.add("20261019000009")
    assert "20261019000009" in v.preflight(tmp_path)[0]


def test_preflight_masks_connection_error(tmp_path):
    class Down(FakeDb):
        def applied_versions(self):
            raise OSError(f"cannot connect {URL}")

    problems = make_verifier(Down([])).preflight(tmp_path)
    assert "접속하지 못했다" in problems[0] and "s3cr" not in problems[0]


def test_install_and_test_get_no_api_key(tmp_path):
    app = make_app(tmp_path, {"20261019000000_init.sql": "create schema if not exists raw;"})
    db = FakeDb([[0, 0, 0], [5, 5, 2], [5, 5, 2]])
    s = spec(install_cmd='test -z "$AIR_API_KEY"', test_cmd='test -z "$AIR_API_KEY" && test -z "$DATABASE_URL"')
    result = make_verifier(db).verify(app, s, tmp_path, "c", 2)
    assert result.ok, result.report()
