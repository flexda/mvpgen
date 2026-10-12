import asyncio

from mvpgen.gates import StopGate

STOP = {"hook_event_name": "Stop", "stop_hook_active": False}


def test_gate_allows_stop_when_check_passes():
    gate = StopGate("t", lambda: (True, "ok"))
    assert asyncio.run(gate(STOP, None, None)) == {}
    assert gate.stats() == {"checks": 1, "blocks": 0, "last_ok": True}


def test_gate_blocks_until_limit_then_allows():
    gate = StopGate("Build", lambda: (False, "test failed: AC1"), max_blocks=2)
    first = asyncio.run(gate(STOP, None, None))
    assert first["decision"] == "block" and "test failed: AC1" in first["reason"] and "1/2" in first["reason"]
    assert asyncio.run(gate(STOP, None, None))["decision"] == "block"
    third = asyncio.run(gate(STOP, None, None))
    assert "decision" not in third
    assert gate.blocks == 2 and gate.checks == 3


def test_gate_recovers_after_fix():
    results = iter([(False, "broken"), (True, "fixed")])
    gate = StopGate("Build", lambda: next(results))
    assert asyncio.run(gate(STOP, None, None))["decision"] == "block"
    assert asyncio.run(gate(STOP, None, None)) == {}
    assert gate.stats()["last_ok"] is True
