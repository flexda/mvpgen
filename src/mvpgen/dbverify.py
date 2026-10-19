"""LLM 없이 데이터 파이프라인을 실제 Supabase에 적용하고 적재 결과를 확인한다.

마이그레이션은 정식 규칙을 따른다. 한 번 DB에 적용한 파일은 잠그고(sha256), 바꿀 것이 있으면 새 파일을 추가하게 한다.
적용은 Supabase CLI의 `db push`가 맡고, 적용 기록은 DB의 supabase_migrations.schema_migrations에 남는다.
DB 접속 문자열은 에이전트에게 주지 않는다. 이 모듈이 실행하는 db push와 수집 명령에만 넘긴다.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from mvpgen.dataspec import LAYERS, DataSpec
from mvpgen.envfiles import app_env
from mvpgen.verify import StepResult, VerifyResult, run_step

MIGRATIONS_REL = Path("supabase/migrations")
MIGRATION_NAME = re.compile(r"^(\d{14})_[a-z0-9_]+\.sql$")
LEDGER_REL = Path("db/ledger.json")
EVIDENCE_REL = Path("db")
PUSH_TIMEOUT_S = 300
# Supabase가 관리하는 스키마. 마이그레이션이 이 스키마의 객체를 가리키면 막는다
RESERVED_SCHEMA_REF = re.compile(
    r"\b(public|auth|storage|realtime|vault|extensions|graphql|graphql_public|pgsodium|net|cron|supabase_\w+)\s*\.",
    re.IGNORECASE,
)
SCHEMA_STMT = re.compile(r"\b(create|drop|alter)\s+schema\s+(?:if\s+(?:not\s+)?exists\s+)?\"?(\w+)", re.IGNORECASE)


def mask(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def url_secrets(db_url: str) -> list[str]:
    """접속 문자열과 그 안의 비밀번호(인코딩 전후). 보고서와 로그에서 가릴 값이다."""
    values = [db_url]
    password = urlsplit(db_url).password
    if password:
        values += [password, unquote(password)]
    return sorted({v for v in values if len(v) >= 4}, key=len, reverse=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ledger(run_dir: Path) -> dict[str, str]:
    path = run_dir / LEDGER_REL
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_ledger(run_dir: Path, ledger: dict[str, str]) -> None:
    path = run_dir / LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(ledger.items())), indent=2), encoding="utf-8")


def migration_files(app_dir: Path) -> list[Path]:
    d = app_dir / MIGRATIONS_REL
    return sorted(d.glob("*.sql")) if d.is_dir() else []


def check_migrations(app_dir: Path, ledger: dict[str, str]) -> list[str]:
    """적용한 파일이 그대로인지, 새 파일이 규칙(이름, 순서, 허용 스키마)을 지키는지 본다."""
    files = migration_files(app_dir)
    if not files:
        return [f"app/{MIGRATIONS_REL}/에 마이그레이션 파일(.sql)이 없다"]
    problems = []
    by_name = {p.name: p for p in files}
    for p in files:
        if not MIGRATION_NAME.match(p.name):
            problems.append(f"{p.name}: 이름은 <14자리 시각>_<소문자_이름>.sql이어야 한다 (예: 20261019120000_create_raw.sql)")
    for name, digest in ledger.items():
        if name not in by_name:
            problems.append(f"{name}: 이미 DB에 적용한 파일을 지웠다. 되살리고, 바꿀 내용은 새 마이그레이션 파일로 추가하라")
        elif _sha(by_name[name]) != digest:
            problems.append(f"{name}: 이미 DB에 적용한 파일을 고쳤다. 원래대로 되돌리고, 바꿀 내용은 새 마이그레이션 파일로 추가하라")
    applied_versions = [MIGRATION_NAME.match(n).group(1) for n in ledger if MIGRATION_NAME.match(n)]  # type: ignore[union-attr]
    latest = max(applied_versions, default="")
    for p in files:
        m = MIGRATION_NAME.match(p.name)
        if p.name in ledger or not m:
            continue
        if m.group(1) <= latest:
            problems.append(f"{p.name}: 새 파일의 시각이 이미 적용한 마지막 파일({latest})보다 늦어야 한다")
        sql = p.read_text(encoding="utf-8")
        for verb, schema in SCHEMA_STMT.findall(sql):
            if verb.lower() == "drop":
                problems.append(f"{p.name}: DROP SCHEMA는 쓸 수 없다")
            elif schema.lower() not in LAYERS:
                problems.append(f"{p.name}: 스키마 {schema}는 쓸 수 없다. {', '.join(LAYERS)}만 쓴다")
        ref = RESERVED_SCHEMA_REF.search(sql)
        if ref:
            problems.append(f"{p.name}: Supabase 관리 스키마({ref.group(1)})의 객체를 건드릴 수 없다")
    return problems


class Database(Protocol):
    def applied_versions(self) -> set[str]: ...
    def counts(self, tables: list[str]) -> dict[str, int | None]: ...
    def violations(self, query: str) -> int: ...
    def schemas(self, names: tuple[str, ...]) -> set[str]: ...


class PgDatabase:
    """psycopg로 Supabase에 붙는다. Session pooler 주소를 전제로 하지만, transaction pooler에서도 돌도록 prepare를 끈다."""

    def __init__(self, url: str) -> None:
        self.url = url

    def _connect(self, autocommit: bool = True):
        import psycopg

        return psycopg.connect(self.url, connect_timeout=15, prepare_threshold=None, autocommit=autocommit)

    def applied_versions(self) -> set[str]:
        with self._connect() as conn:
            if conn.execute("select to_regclass('supabase_migrations.schema_migrations')").fetchone()[0] is None:
                return set()
            return {r[0] for r in conn.execute("select version from supabase_migrations.schema_migrations")}

    def counts(self, tables: list[str]) -> dict[str, int | None]:
        from psycopg import sql

        out: dict[str, int | None] = {}
        with self._connect() as conn:
            for t in tables:
                if conn.execute("select to_regclass(%s)", (t,)).fetchone()[0] is None:
                    out[t] = None
                    continue
                schema, name = t.split(".", 1)
                q = sql.SQL("select count(*) from {}.{}").format(sql.Identifier(schema), sql.Identifier(name))
                out[t] = conn.execute(q).fetchone()[0]
        return out

    def schemas(self, names: tuple[str, ...]) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("select nspname from pg_namespace where nspname = any(%s)", (list(names),))
            return {r[0] for r in rows}

    def violations(self, query: str) -> int:
        body = query.strip().rstrip(";")
        with self._connect(autocommit=False) as conn:
            conn.execute("set transaction read only")
            conn.execute("set local statement_timeout = '30s'")
            n = conn.execute(f"select count(*) from ({body}) as violations").fetchone()[0]  # type: ignore[arg-type]
            conn.rollback()
        return int(n)


@dataclass
class DbVerifier:
    db_url: str
    supabase_bin: str
    # 수집 명령에 넘길 외부 API 키 (mvp.env)
    extra_env: dict[str, str] = field(default_factory=dict)
    db: Database | None = None
    # 테스트에서 실제 CLI 대신 쓸 함수. (app_dir, env) -> StepResult
    push: Callable[[Path, dict[str, str]], StepResult] | None = None

    def __post_init__(self) -> None:
        self.secrets = url_secrets(self.db_url)
        if self.db is None:
            self.db = PgDatabase(self.db_url)

    def _step(self, name: str, ok: bool, detail: str, start: float) -> StepResult:
        return StepResult(name, ok, None, mask(detail, self.secrets), time.monotonic() - start)

    def _masked(self, step: StepResult) -> StepResult:
        step.output_tail = mask(step.output_tail, self.secrets)
        return step

    def _db_push(self, app_dir: Path, env: dict[str, str]) -> StepResult:
        if self.push is not None:
            return self.push(app_dir, env)
        cmd = f"{shlex.quote(self.supabase_bin)} db push --db-url {shlex.quote(self.db_url)} --workdir . --yes"
        return run_step("db push", cmd, app_dir, PUSH_TIMEOUT_S, env)

    def _lock_applied(self, app_dir: Path, run_dir: Path, pushed: bool) -> tuple[bool, str]:
        """DB에 기록된 버전의 파일을 잠근다. db push가 중간에 실패해도 실제로 적용된 파일까지만 잠근다.

        push가 성공했는데 적용 기록에 없는 파일이 있으면 실패로 본다. 버전 형식 가정이 틀려 아무것도 잠기지 않는 일을 막는다.
        """
        assert self.db is not None
        try:
            applied = self.db.applied_versions()
        except Exception as e:
            return False, mask(f"적용 기록을 읽지 못했다: {e!r}", self.secrets)
        ledger = load_ledger(run_dir)
        unrecorded = []
        for p in migration_files(app_dir):
            m = MIGRATION_NAME.match(p.name)
            if not m:
                continue
            if m.group(1) in applied:
                ledger.setdefault(p.name, _sha(p))
            else:
                unrecorded.append(p.name)
        save_ledger(run_dir, ledger)
        if pushed and unrecorded:
            return False, (f"db push는 성공했는데 적용 기록(supabase_migrations.schema_migrations)에 없는 파일이 있다: {unrecorded}. "
                           f"기록된 버전 예: {sorted(applied)[:5]}. mvpgen의 잠금 가정을 확인해야 한다")
        return True, f"적용된 마이그레이션 {len(ledger)}개를 잠갔다"

    def preflight(self, run_dir: Path) -> list[str]:
        """에이전트를 부르기 전에 DB 접속과 상태를 확인한다. 새 실행은 빈 DB, 이어하기는 이 실행의 잠금 목록과 같은 기록이어야 한다."""
        assert self.db is not None
        try:
            applied = self.db.applied_versions()
            existing = self.db.schemas(LAYERS)
        except Exception as e:
            return [mask(f"DB에 접속하지 못했다: {e!r}. Session pooler 문자열과 비밀번호 퍼센트 인코딩을 확인하라", self.secrets)]
        ledger_versions = {m.group(1) for n in load_ledger(run_dir) if (m := MIGRATION_NAME.match(n))}
        if not ledger_versions:
            problems = []
            if applied:
                problems.append(f"새 실행인데 DB에 마이그레이션 기록이 {len(applied)}개 있다 (이전 실행의 것). 새 프로젝트를 쓰거나 기록을 정리하라")
            if existing:
                problems.append(f"새 실행인데 DB에 스키마 {sorted(existing)}가 이미 있다")
            return problems
        if applied != ledger_versions:
            return [f"DB의 마이그레이션 기록이 이 실행의 잠금 목록(db/ledger.json)과 다르다. "
                    f"DB에만 있음 {sorted(applied - ledger_versions)}, 잠금에만 있음 {sorted(ledger_versions - applied)}"]
        return []

    def verify(self, app_dir: Path, spec: DataSpec, run_dir: Path, label: str, page_cap: int | None) -> VerifyResult:
        assert self.db is not None
        result = VerifyResult()
        evidence: dict[str, Any] = {"label": label, "page_cap": page_cap or "전체", "counts": {}, "checks": {}}
        try:
            self._verify(app_dir, spec, run_dir, page_cap, result, evidence)
        finally:
            evidence["steps"] = [{"name": s.name, "ok": s.ok, "detail": s.output_tail} for s in result.steps]
            evidence["ledger"] = sorted(load_ledger(run_dir))
            write_evidence(run_dir, label, evidence)
        return result

    def _verify(self, app_dir: Path, spec: DataSpec, run_dir: Path, page_cap: int | None,
                result: VerifyResult, evidence: dict[str, Any]) -> None:
        assert self.db is not None
        start = time.monotonic()
        if not app_dir.is_dir():
            result.steps.append(self._step("app 디렉토리", False, f"{app_dir}가 없다", start))
            return
        problems = check_migrations(app_dir, load_ledger(run_dir))
        result.steps.append(self._step("migrations", not problems, "\n".join(problems) or "규칙 통과", start))
        if problems:
            return

        # 설치와 테스트에는 DB 접속 문자열을 주지 않는다. 테스트는 네트워크와 DB 없이 통과해야 한다
        offline = {**app_env(self.extra_env), "CI": "1"}
        if spec.install_cmd:
            result.steps.append(self._masked(run_step("install", spec.install_cmd, app_dir, 900, offline)))
            if not result.steps[-1].ok:
                return
        result.steps.append(self._masked(run_step("test", spec.test_cmd, app_dir, 600, offline)))
        if not result.steps[-1].ok:
            return

        push = self._masked(self._db_push(app_dir, app_env({})))
        locked, msg = self._lock_applied(app_dir, run_dir, push.ok)
        push.output_tail += "\n" + msg
        push.ok = push.ok and locked
        result.steps.append(push)
        if not push.ok:
            return

        tables = [t.name for t in spec.tables]
        start = time.monotonic()
        before = self._counts(tables, result, "tables", start)
        if before is None:
            return
        missing = [t for t, n in before.items() if n is None]
        result.steps.append(self._step("tables", not missing,
                                       f"마이그레이션 뒤에도 없는 테이블: {missing}" if missing else f"테이블 {len(tables)}개 확인",
                                       start))
        if missing:
            return

        online = {**app_env(self.extra_env), "DATABASE_URL": self.db_url, spec.page_cap_env: str(page_cap or 0)}
        runs = []
        for n in (1, 2):
            step = self._masked(run_step(f"ingest {n}", spec.ingest_cmd, app_dir, spec.ingest_timeout, online))
            result.steps.append(step)
            if not step.ok:
                return
            counts = self._counts(tables, result, f"ingest {n} 행 수", time.monotonic())
            if counts is None:
                return
            runs.append(counts)
        evidence["counts"] = {t: {"before": before[t], "ingest1": runs[0][t], "ingest2": runs[1][t]} for t in tables}

        start = time.monotonic()
        lines, bad = [], []
        for t in spec.tables:
            c1, c2 = runs[0][t.name], runs[1][t.name]
            lines.append(f"- {t.name}: 적재 전 {before[t.name]}, 1회 {c1}, 2회 {c2}")
            if not c1:
                bad.append(f"{t.name}: 첫 적재 뒤 행이 없다")
            elif t.idempotent and c1 != c2:
                bad.append(f"{t.name}: 같은 데이터를 두 번 적재했더니 행 수가 {c1} -> {c2}로 바뀌었다 (멱등이 아니다)")
        result.steps.append(self._step("idempotency", not bad, "\n".join(bad + [""] + lines), start))
        if bad:
            return

        start = time.monotonic()
        lines, bad = [], []
        for c in spec.checks:
            try:
                n = self.db.violations(c.sql)
            except Exception as e:
                evidence["checks"][c.id] = f"오류: {e!r}"
                bad.append(f"{c.id}: 쿼리 오류 {e!r}")
                continue
            evidence["checks"][c.id] = n
            lines.append(f"- {c.id} ({c.description}): 위반 {n}행")
            if n:
                bad.append(f"{c.id}: 위반 {n}행 ({c.description})")
        result.steps.append(self._step("checks", not bad, "\n".join(bad + [""] + lines), start))

    def _counts(self, tables: list[str], result: VerifyResult, name: str, start: float) -> dict[str, int | None] | None:
        assert self.db is not None
        try:
            return self.db.counts(tables)
        except Exception as e:
            result.steps.append(self._step(name, False, f"DB에서 행 수를 읽지 못했다: {e!r}", start))
            return None


def write_evidence(run_dir: Path, label: str, evidence: dict[str, Any]) -> Path:
    """critic이 읽을 검사 근거. DB 접속 정보는 들어가지 않는다."""
    d = run_dir / EVIDENCE_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{label}.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# DB 검사 결과: {label}", "", f"수집 페이지 제한: {evidence['page_cap']}", "", "## 단계", ""]
    for s in evidence.get("steps", []):
        lines += [f"### {s['name']}: {'통과' if s['ok'] else '실패'}", "", "```", s["detail"].strip(), "```", ""]
    if evidence["counts"]:
        lines += ["## 행 수", "", "| 테이블 | 적재 전 | 1회 | 2회 |", "| --- | --- | --- | --- |"]
        lines += [f"| {t} | {c['before']} | {c['ingest1']} | {c['ingest2']} |" for t, c in evidence["counts"].items()]
        lines.append("")
    if evidence["checks"]:
        lines += ["## 품질 검사 (위반 행 수)", ""] + [f"- {k}: {v}" for k, v in evidence["checks"].items()] + [""]
    lines += ["## 잠긴 마이그레이션", ""] + [f"- {n}" for n in evidence.get("ledger", [])] + [""]
    path = d / f"{label}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
