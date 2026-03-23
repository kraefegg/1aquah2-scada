"""
AquaH2 AI-SCADA — Self-Test Script
Validates all modules without hardware or network.
Run: python test_system.py

Kraefegg M.O. · Developer: Railson
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(__file__))

PASS = "PASS"
FAIL = "FAIL"
results = []


def test(name, fn):
    try:
        fn()
        results.append((PASS, name))
        print(f"  [PASS] {name}")
    except Exception as e:
        results.append((FAIL, name, str(e)))
        print(f"  [FAIL] {name}: {e}")


print("\n" + "="*60)
print("  AquaH2 AI-SCADA — Self-Test")
print("  Kraefegg M.O. · Developer: Railson")
print("="*60)

# ── 1. Config ─────────────────────────────────────────────────────────
print("\n[1] Config module...")
def t_config():
    from config import LIMITS, SETPOINTS, ALARM_CODES
    assert LIMITS["stack_temp_nominal"] == (60.0, 80.0)
    assert SETPOINTS["stack_a_power_pct"] == 86.0
    assert "ALM-0001" in ALARM_CODES
test("Config loads correctly", t_config)

# ── 2. Simulator ──────────────────────────────────────────────────────
print("\n[2] Simulator module...")
def t_sim_init():
    from simulator import SimulatedPlant
    p = SimulatedPlant()
    assert p.state.stack_a.id == "A"
    assert p.state.swro.enabled is True
test("Plant initializes", t_sim_init)

def t_sim_tick():
    from simulator import SimulatedPlant
    p = SimulatedPlant()
    state = p.tick()
    assert 60 <= state.stack_a.temp_cell <= 90
    assert 0 <= state.energy.solar_mw <= 30
    assert 0 <= state.bess.soc <= 100
test("Simulator tick produces valid values", t_sim_tick)

def t_sim_setpoint():
    from simulator import SimulatedPlant
    p = SimulatedPlant()
    ok = p.apply_setpoint("stack_a_water_flow", 25.0)
    assert ok is True
    assert p.get_setpoints()["stack_a_water_flow"] == 25.0
test("Setpoint application", t_sim_setpoint)

def t_sim_toggle():
    from simulator import SimulatedPlant
    p = SimulatedPlant()
    ok = p.apply_toggle("stack_b", False)
    assert ok is True
    p.tick()
    assert p.state.stack_b.h2_production == 0.0
test("Toggle disables stack", t_sim_toggle)

def t_sim_esd():
    from simulator import SimulatedPlant
    p = SimulatedPlant()
    msg = p.trigger_esd()
    assert p.state.safety.esd_triggered is True
    assert p.state.stack_a.enabled is False
    msg2 = p.reset_esd()
    assert p.state.safety.esd_triggered is False
    assert p.state.stack_a.enabled is True
test("ESD trigger and reset", t_sim_esd)

def t_sim_serialization():
    from simulator import SimulatedPlant
    p = SimulatedPlant()
    p.tick()
    d = p.to_dict()
    s = json.dumps(d)
    d2 = json.loads(s)
    assert "stack_a" in d2
    assert "energy" in d2
    assert "safety" in d2
    assert isinstance(d2["stack_a"]["temp_cell"], float)
test("Plant state serializes to JSON", t_sim_serialization)

def t_sim_network():
    from simulator import SimulatedPlant
    p = SimulatedPlant()
    net = p.get_network_status()
    assert "ai-edge" in net
    assert "plc-elec" in net
    assert net["wifi-ap-03"]["latency_ms"] > 50  # known bad node
test("Network topology", t_sim_network)

# ── 3. Database ───────────────────────────────────────────────────────
print("\n[3] Database module...")
TEST_DB = "/tmp/aquah2_test.db"

def t_db_init():
    from database import Database
    db = Database(TEST_DB)
    stats = db.get_stats()
    assert "sensor_history" in stats
test("Database initializes", t_db_init)

def t_db_write_read():
    from simulator import SimulatedPlant
    from database import Database
    p = SimulatedPlant()
    db = Database(TEST_DB)
    for _ in range(5):
        p.tick()
        db.record_sensors(p.to_dict())
    history = db.get_history("stack_a_temp", hours=1)
    assert len(history) >= 5
    assert all("ts" in r and "value" in r for r in history)
test("Sensor write and read", t_db_write_read)

def t_db_events():
    from database import Database
    db = Database(TEST_DB)
    db.record_event("warn", "TEST-001", "Test event", "detail here")
    events = db.get_events(limit=5)
    assert len(events) >= 1
    assert events[0]["code"] == "TEST-001"
test("Event log write and read", t_db_events)

def t_db_setpoint_log():
    from database import Database
    db = Database(TEST_DB)
    db.record_setpoint("stack_a_water_flow", 22.0, 24.5, "operator")
    log = db.get_setpoint_log(limit=5)
    assert len(log) >= 1
    assert log[0]["tag"] == "stack_a_water_flow"
test("Setpoint log", t_db_setpoint_log)

def t_db_trim():
    from database import Database
    db = Database(TEST_DB)
    deleted = db.trim_old_data(retention_hours=0.001)
    assert isinstance(deleted, int)
test("Database trim old data", t_db_trim)

# ── 4. AI Engine ──────────────────────────────────────────────────────
print("\n[4] AI Engine module...")

def t_ai_init():
    from simulator import SimulatedPlant
    from ai_engine import AquaH2AIEngine
    p = SimulatedPlant()
    ai = AquaH2AIEngine(p)
    assert ai._ai_enabled is True
    assert len(ai.active_alarms) == 0
test("AI engine initializes", t_ai_init)

def t_ai_rolling_stats():
    from ai_engine import RollingStats
    rs = RollingStats(window=10)
    for i in range(10):
        rs.push(float(i))
    assert abs(rs.mean() - 4.5) < 0.01
    assert rs.slope() > 0
    z = rs.zscore(100.0)
    assert z > 2.0
test("Rolling statistics", t_ai_rolling_stats)

def t_ai_pid():
    from ai_engine import PIDController
    pid = PIDController(kp=1.0, ki=0.1, kd=0.0, output_min=0, output_max=100)
    out = pid.update(setpoint=50.0, measured=40.0)
    assert out > 0
    pid.reset()
test("PID controller", t_ai_pid)

def t_ai_alarm():
    from simulator import SimulatedPlant
    from ai_engine import AquaH2AIEngine
    p = SimulatedPlant()
    ai = AquaH2AIEngine(p)
    # Force a high temperature
    p.state.stack_a.temp_cell = 83.0  # above trip level
    decisions = ai.analyze_and_decide()
    # Should have generated an alarm
    assert "ALM-0003" in ai.active_alarms or len(decisions) > 0
test("AI generates alarm on limit violation", t_ai_alarm)

def t_ai_ingest():
    from simulator import SimulatedPlant
    from ai_engine import AquaH2AIEngine
    p = SimulatedPlant()
    ai = AquaH2AIEngine(p)
    for _ in range(35):
        state = p.tick()
        ai.ingest(state)
    # Should have enough data for anomaly detection
    assert len(ai._stats["stack_a_temp"]._data) == 30  # window size
test("AI ingest fills rolling window", t_ai_ingest)

def t_ai_chat_builtin():
    import asyncio
    from simulator import SimulatedPlant
    from ai_engine import AquaH2AIEngine
    p = SimulatedPlant()
    p.tick()
    ai = AquaH2AIEngine(p)
    # Use built-in responses (no API key)
    resp = asyncio.run(ai.chat("status geral da planta"))
    assert len(resp) > 20
    assert "Stack" in resp or "produção" in resp or "MW" in resp
test("AI chat built-in response", t_ai_chat_builtin)

def t_ai_decisions():
    from simulator import SimulatedPlant
    from ai_engine import AquaH2AIEngine
    p = SimulatedPlant()
    ai = AquaH2AIEngine(p)
    for _ in range(10):
        state = p.tick()
        ai.ingest(state)
    decisions = ai.analyze_and_decide()
    assert isinstance(decisions, list)
    for d in decisions:
        assert d.action_type in ("setpoint", "toggle", "alert", "info")
        assert 0.0 <= d.confidence <= 1.0
test("AI decisions format", t_ai_decisions)

# ── 5. Integration test ───────────────────────────────────────────────
print("\n[5] Integration test...")

def t_integration_full():
    """Simulate 60 seconds of plant operation with full stack."""
    from simulator import SimulatedPlant
    from ai_engine import AquaH2AIEngine
    from database import Database

    p = SimulatedPlant()
    ai = AquaH2AIEngine(p)
    db = Database(TEST_DB)

    for tick in range(30):
        state = p.tick()
        data = p.to_dict()
        ai.ingest(state)

        if tick % 5 == 0:
            db.record_sensors(data)

        decisions = ai.analyze_and_decide()
        for d in decisions:
            if d.action_type == "setpoint":
                p.apply_setpoint(d.target, d.value)
            elif d.action_type == "toggle":
                p.apply_toggle(d.target, d.value)

    # Final checks
    assert 50 <= p.state.stack_a.temp_cell <= 95
    assert 0 <= p.state.bess.soc <= 100
    final_data = p.to_dict()
    assert json.dumps(final_data)  # must be serializable

test("Full 30-tick simulation with AI control", t_integration_full)

# ── Cleanup ───────────────────────────────────────────────────────────
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

# ── Summary ───────────────────────────────────────────────────────────
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
total  = len(results)

print(f"\n{'='*60}")
print(f"  Results: {passed}/{total} passed  |  {failed} failed")
print(f"{'='*60}")

if failed > 0:
    print("\nFailed tests:")
    for r in results:
        if r[0] == FAIL:
            print(f"  - {r[1]}: {r[2] if len(r) > 2 else ''}")
    print()
    sys.exit(1)
else:
    print("\n  All tests passed. System ready.")
    print(f"\n  To start the server:")
    print(f"  cd aquah2_backend && python main.py")
    print(f"\n  Then open: http://localhost:8765/")
    print()
    sys.exit(0)
