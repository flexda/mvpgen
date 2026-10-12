from mvpgen.spec import Spec
from mvpgen.verify import run_step, verify_app

from conftest import PY


def make_spec(spec_dict, **over):
    d = {**spec_dict, "install_cmd": None, "test_cmd": "true", "startup_timeout": 15, **over}
    return Spec.model_validate(d)


def test_run_step_success_and_failure(tmp_path):
    assert run_step("ok", "echo hi", tmp_path, 10).ok
    bad = run_step("bad", "echo boom >&2; exit 3", tmp_path, 10)
    assert not bad.ok and bad.returncode == 3 and "boom" in bad.output_tail


def test_run_step_timeout(tmp_path):
    r = run_step("slow", "sleep 5", tmp_path, 0.5)
    assert not r.ok and "끝나지 않았다" in r.output_tail


def test_verify_server_app_passes(spec_dict, python_server_app):
    spec = make_spec(spec_dict, run_cmd=f"{PY} server.py",
                     smoke={"url": "http://127.0.0.1:{port}/", "expect": "Hello MVP"})
    result = verify_app(python_server_app, spec)
    assert result.ok, result.report()
    assert [s.name for s in result.steps] == ["test", "run+smoke"]


def test_verify_stops_at_failing_tests(spec_dict, python_server_app):
    spec = make_spec(spec_dict, test_cmd="echo 'AssertionError in test_x'; exit 1", run_cmd=f"{PY} server.py")
    result = verify_app(python_server_app, spec)
    assert not result.ok
    assert result.failed_step.name == "test"
    assert "AssertionError" in result.report()


def test_verify_smoke_expect_mismatch(spec_dict, python_server_app):
    spec = make_spec(spec_dict, run_cmd=f"{PY} server.py", startup_timeout=5,
                     smoke={"url": "http://127.0.0.1:{port}/", "expect": "Not There"})
    result = verify_app(python_server_app, spec)
    assert not result.ok and result.failed_step.name == "run+smoke"


def test_verify_crashing_app(spec_dict, python_server_app):
    spec = make_spec(spec_dict, run_cmd=f"{PY} -c 'raise SystemExit(4)'")
    result = verify_app(python_server_app, spec)
    assert not result.ok and "먼저 끝났다" in result.report()


def test_verify_command_smoke(spec_dict, python_server_app):
    spec = make_spec(spec_dict, run_cmd="sleep 30", smoke={"command": "echo ready", "expect": "ready"})
    assert verify_app(python_server_app, spec).ok
