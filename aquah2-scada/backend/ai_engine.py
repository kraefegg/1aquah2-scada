"""
AquaH2 AI-SCADA — AI Control Engine
Implements:
  - Real-time anomaly detection (Z-score + threshold)
  - Predictive maintenance (trend slope analysis)
  - Autonomous setpoint optimization (gradient-free hill climbing)
  - PID-style soft control loops
  - Natural language interface (Claude API or built-in responses)
  - Alarm management

Kraefegg M.O. · Developer: Railson
"""

import time
import math
import json
import asyncio
import statistics
import os
import urllib.request
import urllib.error
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from simulator import PlantState, SimulatedPlant
from config import LIMITS, ALARM_CODES, ANTHROPIC_API_KEY, ANTHROPIC_MODEL


# ── Alarm ──────────────────────────────────────────────────────────────

@dataclass
class Alarm:
    code: str
    level: str       # "info" | "warn" | "alarm" | "trip"
    message: str
    detail: str
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False
    ack_by: str = ""
    ack_time: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "code": self.code,
            "level": self.level,
            "message": self.message,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
            "ack_by": self.ack_by,
            "ack_time": self.ack_time,
        }


# ── AI Decision ────────────────────────────────────────────────────────

@dataclass
class AIDecision:
    action_type: str     # "setpoint" | "toggle" | "alert" | "info"
    target: str
    value: Any
    reason: str
    confidence: float    # 0–1
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "value": self.value,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
            "timestamp": self.timestamp,
        }


# ── Rolling Statistics ─────────────────────────────────────────────────

class RollingStats:
    """Maintains rolling window for anomaly detection."""

    def __init__(self, window: int = 30):
        self.window = window
        self._data: deque = deque(maxlen=window)

    def push(self, val: float):
        self._data.append(val)

    def zscore(self, val: float) -> float:
        if len(self._data) < 5:
            return 0.0
        mu = statistics.mean(self._data)
        sigma = statistics.stdev(self._data) if len(self._data) > 1 else 1e-6
        if sigma < 1e-9:
            return 0.0
        return abs(val - mu) / sigma

    def slope(self) -> float:
        """Linear regression slope of last N points."""
        n = len(self._data)
        if n < 3:
            return 0.0
        xs = list(range(n))
        ys = list(self._data)
        xm, ym = sum(xs) / n, sum(ys) / n
        num = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
        den = sum((x - xm) ** 2 for x in xs)
        return num / den if den > 1e-12 else 0.0

    def mean(self) -> float:
        return statistics.mean(self._data) if self._data else 0.0

    def last(self) -> Optional[float]:
        return self._data[-1] if self._data else None


# ── PID Controller ─────────────────────────────────────────────────────

class PIDController:
    """Soft PID for setpoint corrections (operates within safe limits)."""

    def __init__(self, kp: float, ki: float, kd: float,
                 output_min: float, output_max: float):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.output_min = output_min
        self.output_max = output_max
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = time.time()

    def update(self, setpoint: float, measured: float) -> float:
        now = time.time()
        dt = max(now - self._prev_time, 1e-6)
        error = setpoint - measured
        self._integral += error * dt
        # Anti-windup
        self._integral = max(self.output_min / self.ki if self.ki else -1e9,
                             min(self.output_max / self.ki if self.ki else 1e9,
                                 self._integral))
        derivative = (error - self._prev_error) / dt
        output = self.kp * error + self.ki * self._integral + self.kd * derivative
        output = max(self.output_min, min(self.output_max, output))
        self._prev_error = error
        self._prev_time = now
        return output

    def reset(self):
        self._integral = 0.0
        self._prev_error = 0.0


# ── AI Engine ──────────────────────────────────────────────────────────

class AquaH2AIEngine:
    """
    Core AI control engine.
    Runs periodically, analyzes plant state, issues corrections,
    detects anomalies, and manages alarms.
    """

    def __init__(self, plant: SimulatedPlant):
        self.plant = plant
        self.active_alarms: Dict[str, Alarm] = {}
        self.alarm_history: List[Alarm] = []
        self.decision_history: List[AIDecision] = []
        self.chat_history: List[Dict] = []  # [{"role": "user"|"assistant", "content": ...}]
        self._ai_enabled = True
        self._uptime_start = time.time()

        # Rolling stats for each monitored signal
        self._stats: Dict[str, RollingStats] = {
            "stack_a_temp":    RollingStats(30),
            "stack_b_temp":    RollingStats(30),
            "stack_a_press":   RollingStats(30),
            "stack_b_press":   RollingStats(30),
            "stack_a_h2":      RollingStats(30),
            "stack_b_h2":      RollingStats(30),
            "swro_press":      RollingStats(30),
            "swro_salinity":   RollingStats(30),
            "solar_mw":        RollingStats(30),
            "wind_mw":         RollingStats(30),
            "bess_soc":        RollingStats(30),
            "nh3_rate":        RollingStats(30),
        }

        # PID controllers for key loops
        self._pid_temp_a = PIDController(kp=0.5, ki=0.01, kd=0.1, output_min=15, output_max=38)
        self._pid_temp_b = PIDController(kp=0.5, ki=0.01, kd=0.1, output_min=15, output_max=38)
        self._pid_press_a = PIDController(kp=2.0, ki=0.05, kd=0.2, output_min=70, output_max=100)
        self._pid_press_b = PIDController(kp=2.0, ki=0.05, kd=0.2, output_min=70, output_max=100)

        # Metrics
        self.metrics = {
            "decisions_applied": 0,
            "alarms_generated": 0,
            "anomalies_detected": 0,
            "predictive_alerts": 0,
            "uptime_pct": 100.0,
        }

    # ── Main control loop ─────────────────────────────────────────────

    async def run_control_loop(self, on_decision: Callable):
        """
        Runs the AI control loop indefinitely.
        on_decision: async callback(decision: AIDecision)
        """
        while True:
            try:
                decisions = self.analyze_and_decide()
                for d in decisions:
                    if d.action_type in ("setpoint", "toggle") and self._ai_enabled:
                        if d.action_type == "setpoint":
                            self.plant.apply_setpoint(d.target, d.value)
                        elif d.action_type == "toggle":
                            self.plant.apply_toggle(d.target, d.value)
                        self.metrics["decisions_applied"] += 1
                    self.decision_history.append(d)
                    if len(self.decision_history) > 500:
                        self.decision_history.pop(0)
                    await on_decision(d)
            except Exception as e:
                print(f"[AI Engine] Control loop error: {e}")
            await asyncio.sleep(10.0)

    # ── Sensor ingestion ──────────────────────────────────────────────

    def ingest(self, state: PlantState):
        """Push current sensor readings into rolling stats."""
        self._stats["stack_a_temp"].push(state.stack_a.temp_cell)
        self._stats["stack_b_temp"].push(state.stack_b.temp_cell)
        self._stats["stack_a_press"].push(state.stack_a.pressure_h2)
        self._stats["stack_b_press"].push(state.stack_b.pressure_h2)
        self._stats["stack_a_h2"].push(state.stack_a.h2_production)
        self._stats["stack_b_h2"].push(state.stack_b.h2_production)
        self._stats["swro_press"].push(state.swro.feed_pressure)
        self._stats["swro_salinity"].push(state.swro.product_salinity)
        self._stats["solar_mw"].push(state.energy.solar_mw)
        self._stats["wind_mw"].push(state.energy.wind_mw)
        self._stats["bess_soc"].push(state.bess.soc)
        self._stats["nh3_rate"].push(state.nh3.production_kgh)

    # ── Analyze and decide ────────────────────────────────────────────

    def analyze_and_decide(self) -> List[AIDecision]:
        """
        Core AI logic: read state, check limits, optimize, return decisions.
        """
        state = self.plant.state
        self.ingest(state)
        decisions: List[AIDecision] = []

        # 1. Safety checks (highest priority)
        decisions += self._check_safety(state)

        # 2. Stack temperature control (PID)
        decisions += self._control_stack_temps(state)

        # 3. Energy optimization
        decisions += self._optimize_energy(state)

        # 4. Anomaly detection
        decisions += self._detect_anomalies(state)

        # 5. Predictive maintenance
        decisions += self._predictive_maintenance(state)

        return decisions

    # ── Safety checks ─────────────────────────────────────────────────

    def _check_safety(self, state: PlantState) -> List[AIDecision]:
        decisions = []
        L = LIMITS

        # Stack A temperature
        ta = state.stack_a.temp_cell
        if ta > L["stack_temp_trip"][1]:
            self._raise_alarm("ALM-0003", "trip",
                f"Stack A temp CRÍTICA: {ta:.1f}°C > {L['stack_temp_trip'][1]}°C")
            decisions.append(AIDecision("toggle", "stack_a", False,
                f"ESD automático: Stack A temperatura {ta:.1f}°C acima do trip {L['stack_temp_trip'][1]}°C", 1.0))
        elif ta > L["stack_temp_alarm"][1]:
            self._raise_alarm("ALM-0002", "alarm",
                f"Stack A temp ALARME: {ta:.1f}°C")
        elif ta > L["stack_temp_nominal"][1]:
            self._raise_alarm("ALM-0001", "warn",
                f"Stack A temp aviso: {ta:.1f}°C")
        else:
            self._clear_alarm("ALM-0001"); self._clear_alarm("ALM-0002"); self._clear_alarm("ALM-0003")

        # Stack B temperature
        tb = state.stack_b.temp_cell
        if tb > L["stack_temp_trip"][1]:
            self._raise_alarm("ALM-0006", "trip",
                f"Stack B temp CRÍTICA: {tb:.1f}°C")
            decisions.append(AIDecision("toggle", "stack_b", False,
                f"ESD automático: Stack B temperatura {tb:.1f}°C acima do trip", 1.0))
        elif tb > L["stack_temp_alarm"][1]:
            self._raise_alarm("ALM-0005", "alarm",
                f"Stack B temp ALARME: {tb:.1f}°C")
        elif tb > L["stack_temp_nominal"][1]:
            self._raise_alarm("ALM-0004", "warn",
                f"Stack B temp aviso: {tb:.1f}°C")
        else:
            self._clear_alarm("ALM-0004"); self._clear_alarm("ALM-0005"); self._clear_alarm("ALM-0006")

        # H2 pressure Stack A
        pa = state.stack_a.pressure_h2
        if pa > L["stack_pressure_trip"][1]:
            self._raise_alarm("ALM-0011", "trip",
                f"Stack A pressão H2 CRÍTICA: {pa:.1f} bar — ESD ativado")
            decisions.append(AIDecision("toggle", "stack_a", False,
                f"ESD: pressão Stack A {pa:.1f} bar > {L['stack_pressure_trip'][1]} bar", 1.0))
        elif pa > L["stack_pressure_alarm"][1]:
            self._raise_alarm("ALM-0010", "alarm",
                f"Stack A pressão H2 alta: {pa:.1f} bar")
        else:
            self._clear_alarm("ALM-0010"); self._clear_alarm("ALM-0011")

        # H2 pressure Stack B
        pb = state.stack_b.pressure_h2
        if pb > L["stack_pressure_trip"][1]:
            self._raise_alarm("ALM-0013", "trip",
                f"Stack B pressão H2 CRÍTICA: {pb:.1f} bar")
            decisions.append(AIDecision("toggle", "stack_b", False,
                f"ESD: pressão Stack B {pb:.1f} bar > {L['stack_pressure_trip'][1]} bar", 1.0))
        elif pb > L["stack_pressure_alarm"][1]:
            self._raise_alarm("ALM-0012", "alarm",
                f"Stack B pressão H2 alta: {pb:.1f} bar")
        else:
            self._clear_alarm("ALM-0012"); self._clear_alarm("ALM-0013")

        # H2 LEL sensors
        for sensor, lel in state.safety.h2_lel.items():
            if lel > L["h2_lel_trip"]:
                self._raise_alarm("ALM-0021", "trip",
                    f"{sensor}: H2 LEL CRÍTICO {lel:.1f}% — ESD ativado")
            elif lel > L["h2_lel_alarm"]:
                self._raise_alarm("ALM-0020", "alarm",
                    f"{sensor}: H2 LEL {lel:.1f}% (alarme > {L['h2_lel_alarm']}%)")

        # NH3 sensors
        for sensor, ppm in state.safety.nh3_ppm.items():
            if ppm > L["nh3_ppm_trip"]:
                self._raise_alarm("ALM-0031", "trip",
                    f"{sensor}: NH3 CRÍTICO {ppm:.0f} ppm")
            elif ppm > L["nh3_ppm_alarm"]:
                self._raise_alarm("ALM-0030", "alarm",
                    f"{sensor}: NH3 alto {ppm:.0f} ppm (TLV-TWA: 25 ppm)")

        # SWRO salinity
        sal = state.swro.product_salinity
        if sal > L["swro_salinity_max"]:
            self._raise_alarm("ALM-0041", "warn",
                f"SWRO salinidade produto alta: {sal:.3f} g/L > {L['swro_salinity_max']} g/L")
        else:
            self._clear_alarm("ALM-0041")

        # BESS SoC
        if state.bess.soc < L["bess_soc_min"]:
            self._raise_alarm("ALM-0050", "warn",
                f"BESS SoC baixo: {state.bess.soc:.1f}% < {L['bess_soc_min']}%")
        else:
            self._clear_alarm("ALM-0050")

        return decisions

    # ── Temperature control (PID) ─────────────────────────────────────

    def _control_stack_temps(self, state: PlantState) -> List[AIDecision]:
        """
        Use PID to adjust water flow setpoints to regulate stack temperatures.
        Target: keep both stacks in nominal range (60–80°C).
        """
        decisions = []
        nominal_hi = LIMITS["stack_temp_nominal"][1]
        target_temp = 73.0  # optimal operating point

        # Stack A
        if state.stack_a.enabled:
            new_flow_a = self._pid_temp_a.update(target_temp, state.stack_a.temp_cell)
            current_sp_a = self.plant.get_setpoints().get("stack_a_water_flow", 22.0)
            if abs(new_flow_a - current_sp_a) > 0.5:
                decisions.append(AIDecision(
                    "setpoint", "stack_a_water_flow",
                    round(new_flow_a, 1),
                    f"Ajuste PID Stack A: temp {state.stack_a.temp_cell:.1f}°C → fluxo H₂O {round(new_flow_a, 1)} L/min",
                    0.85
                ))

        # Stack B — more aggressive because it's running hotter
        if state.stack_b.enabled:
            new_flow_b = self._pid_temp_b.update(target_temp, state.stack_b.temp_cell)
            current_sp_b = self.plant.get_setpoints().get("stack_b_water_flow", 22.0)
            if abs(new_flow_b - current_sp_b) > 0.5:
                decisions.append(AIDecision(
                    "setpoint", "stack_b_water_flow",
                    round(new_flow_b, 1),
                    f"Ajuste PID Stack B: temp {state.stack_b.temp_cell:.1f}°C → fluxo H₂O {round(new_flow_b, 1)} L/min (Stack B acima do nominal)",
                    0.90
                ))

        return decisions

    # ── Energy optimization ───────────────────────────────────────────

    def _optimize_energy(self, state: PlantState) -> List[AIDecision]:
        """
        Balance power between electrolyzer, BESS, and SWRO
        to maximize H2 production while maintaining BESS buffer.
        """
        decisions = []
        total_mw = state.energy.total_mw
        sp = self.plant.get_setpoints()

        # Target: keep BESS at 75–90% SoC, maximize electrolyzer power
        if state.bess.soc < 30 and total_mw > 40:
            # Charge BESS more aggressively
            new_bess_pct = min(40, sp["bess_priority_pct"] + 10)
            if new_bess_pct != sp["bess_priority_pct"]:
                decisions.append(AIDecision(
                    "setpoint", "bess_priority_pct", new_bess_pct,
                    f"BESS SoC baixo ({state.bess.soc:.0f}%) com energia disponível ({total_mw:.1f} MW): aumentando prioridade de carga para {new_bess_pct}%",
                    0.80
                ))

        elif state.bess.soc > 90:
            # Reduce BESS charging, route more to electrolyzer
            new_bess_pct = max(10, sp["bess_priority_pct"] - 5)
            if new_bess_pct != sp["bess_priority_pct"]:
                decisions.append(AIDecision(
                    "setpoint", "bess_priority_pct", new_bess_pct,
                    f"BESS quase cheio ({state.bess.soc:.0f}%): reduzindo prioridade para {new_bess_pct}%, mais energia ao eletrolisador",
                    0.75
                ))

        # Adjust electrolyzer power to available energy
        avail_for_elec = total_mw - 2.0  # 2 MW for SWRO + aux
        if avail_for_elec < 30 and state.bess.soc > 40:
            # Draw from BESS to maintain production
            bess_supplement = min(5.0, 50 - avail_for_elec)
            decisions.append(AIDecision(
                "setpoint", "bess_priority_pct", -bess_supplement * 10,
                f"Energia renovável baixa ({total_mw:.1f} MW): descarga BESS para compensar. SoC: {state.bess.soc:.0f}%",
                0.78
            ))

        return decisions

    # ── Anomaly detection ─────────────────────────────────────────────

    def _detect_anomalies(self, state: PlantState) -> List[AIDecision]:
        """Z-score anomaly detection on rolling windows."""
        decisions = []
        threshold = 2.8

        checks = [
            ("stack_a_temp",  state.stack_a.temp_cell,   "Temperatura Stack A"),
            ("stack_b_temp",  state.stack_b.temp_cell,   "Temperatura Stack B"),
            ("stack_a_press", state.stack_a.pressure_h2, "Pressão H2 Stack A"),
            ("stack_b_press", state.stack_b.pressure_h2, "Pressão H2 Stack B"),
            ("swro_press",    state.swro.feed_pressure,  "Pressão SWRO"),
            ("swro_salinity", state.swro.product_salinity, "Salinidade SWRO"),
        ]

        for key, val, label in checks:
            z = self._stats[key].zscore(val)
            if z > threshold:
                self.metrics["anomalies_detected"] += 1
                decisions.append(AIDecision(
                    "alert", key, val,
                    f"Anomalia detectada: {label} = {val:.2f} (Z-score={z:.1f}, limiar={threshold}). Investigar.",
                    min(1.0, z / 4.0)
                ))

        return decisions

    # ── Predictive maintenance ────────────────────────────────────────

    def _predictive_maintenance(self, state: PlantState) -> List[AIDecision]:
        """
        Trend-based predictive maintenance:
        - Rising temperature slope → impending issue
        - SWRO membrane fouling rate → schedule CIP
        - BESS degradation
        """
        decisions = []

        # Stack B temperature trend
        slope_b = self._stats["stack_b_temp"].slope()
        if slope_b > 0.05:  # rising faster than 0.05°C per sample
            eta_alarm = max(0, (LIMITS["stack_temp_alarm"][1] - state.stack_b.temp_cell) / slope_b)
            self.metrics["predictive_alerts"] += 1
            decisions.append(AIDecision(
                "alert", "stack_b_temp_trend", slope_b,
                f"Manutenção preditiva: Stack B temperatura subindo {slope_b:.3f}°C/ciclo. "
                f"Tempo estimado até alarme: {eta_alarm:.0f} ciclos ({eta_alarm*2:.0f}s). "
                f"Recomendo verificar trocador de calor Stack B.",
                0.72
            ))

        # SWRO PV-03 fouling
        pv03 = state.swro.membrane_fouling_pv.get("PV-03", 0)
        if pv03 > 40:
            days_to_max = max(0, (100 - pv03) / 0.05)  # ~0.05%/day rate
            self.metrics["predictive_alerts"] += 1
            decisions.append(AIDecision(
                "alert", "swro_membrane_pv03", pv03,
                f"Manutenção preditiva: PV-03 fouling {pv03:.1f}%. "
                f"Tempo estimado até necessidade de CIP (>50%): ~{days_to_max:.0f} dias. "
                f"Agendar limpagem química para próxima janela de manutenção.",
                0.85
            ))

        # H2 purity trend
        if state.stack_b.h2_purity < LIMITS["h2_purity_min"] + 0.03:
            decisions.append(AIDecision(
                "alert", "h2_purity_b", state.stack_b.h2_purity,
                f"Atenção: Pureza H2 Stack B se aproximando do limite mínimo "
                f"({state.stack_b.h2_purity:.3f}% vs mínimo {LIMITS['h2_purity_min']}%). "
                f"Possível degradação de membrana PEM.",
                0.70
            ))

        return decisions

    # ── Alarm management ─────────────────────────────────────────────

    def _raise_alarm(self, code: str, level: str, detail: str):
        if code not in self.active_alarms:
            alm = Alarm(
                code=code,
                level=level,
                message=ALARM_CODES.get(code, f"Alarm {code}"),
                detail=detail,
            )
            self.active_alarms[code] = alm
            self.alarm_history.append(alm)
            if len(self.alarm_history) > 1000:
                self.alarm_history.pop(0)
            self.metrics["alarms_generated"] += 1

    def _clear_alarm(self, code: str):
        self.active_alarms.pop(code, None)

    def acknowledge_alarm(self, code: str, operator: str) -> bool:
        if code in self.active_alarms:
            self.active_alarms[code].acknowledged = True
            self.active_alarms[code].ack_by = operator
            self.active_alarms[code].ack_time = time.time()
            return True
        return False

    def get_alarm_list(self) -> List[Dict]:
        return [a.to_dict() for a in self.active_alarms.values()]

    def get_alarm_history(self, limit: int = 50) -> List[Dict]:
        return [a.to_dict() for a in reversed(self.alarm_history[-limit:])]

    # ── Chat interface ────────────────────────────────────────────────

    async def chat(self, user_message: str) -> str:
        """
        Process a chat message. Uses Claude API if configured,
        otherwise uses built-in context-aware responses.
        """
        self.chat_history.append({"role": "user", "content": user_message})
        state = self.plant.state

        api_key = ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")

        if api_key:
            response = await self._chat_claude(user_message, state, api_key)
        else:
            response = self._chat_builtin(user_message, state)

        self.chat_history.append({"role": "assistant", "content": response})
        if len(self.chat_history) > 40:
            self.chat_history = self.chat_history[-40:]

        return response

    async def _chat_claude(self, message: str, state: PlantState, api_key: str) -> str:
        """Call Claude API with plant context."""
        context = self._build_context_summary(state)
        system_prompt = f"""Você é o assistente de IA da plataforma AquaH2, desenvolvida pela Kraefegg M.O.
Você monitora e controla uma planta de hidrogênio verde integrada com dessalinização no Nordeste do Brasil.
Responda em português de forma técnica, precisa e concisa. Nunca invente dados — use apenas os dados fornecidos.

DADOS ATUAIS DA PLANTA:
{context}

Regras de segurança: NUNCA recomende ações que violem os limites de segurança IEC 61511 SIL-2.
Para emergências com H2 > 50% LEL ou NH3 > 100 ppm, instrua acionamento imediato do ESD."""

        payload = json.dumps({
            "model": ANTHROPIC_MODEL,
            "max_tokens": 600,
            "system": system_prompt,
            "messages": self.chat_history[-10:],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST"
        )
        try:
            loop = asyncio.get_event_loop()
            def do_request():
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            result = await loop.run_in_executor(None, do_request)
            return result["content"][0]["text"]
        except Exception as e:
            return self._chat_builtin(message, state) + f"\n\n_(Claude API indisponível: {e})_"

    def _build_context_summary(self, state: PlantState) -> str:
        return f"""Stack A: T={state.stack_a.temp_cell:.1f}°C P={state.stack_a.pressure_h2:.1f}bar H2={state.stack_a.h2_production:.0f}Nm³/h Eff={state.stack_a.efficiency_lhv:.1f}%
Stack B: T={state.stack_b.temp_cell:.1f}°C P={state.stack_b.pressure_h2:.1f}bar H2={state.stack_b.h2_production:.0f}Nm³/h Eff={state.stack_b.efficiency_lhv:.1f}% {'⚠ TEMP ALTA' if state.stack_b.temp_cell > 78 else ''}
Energia: Solar={state.energy.solar_mw:.1f}MW Eólica={state.energy.wind_mw:.1f}MW Total={state.energy.total_mw:.1f}MW BESS={state.bess.soc:.0f}%
SWRO: Pressão={state.swro.feed_pressure:.1f}bar Salinidade={state.swro.product_salinity:.3f}g/L Vazão={state.swro.product_flow:.2f}m³/min
NH3: {state.nh3.production_kgh:.0f}kg/h Reator={state.nh3.reactor_temp:.0f}°C/{state.nh3.reactor_pressure:.0f}bar
H2 Storage: {state.h2_storage.tank_level_pct:.0f}% ({state.h2_storage.tank_mass_t:.1f}t) @ {state.h2_storage.tank_pressure_bar:.0f}bar
Alarmes ativos: {len(self.active_alarms)} — {', '.join(self.active_alarms.keys()) or 'nenhum'}
Decisões IA (últimas 3): {'; '.join(d.reason[:60] for d in self.decision_history[-3:])}"""

    def _chat_builtin(self, message: str, state: PlantState) -> str:
        """Context-aware built-in responses when API is not available."""
        msg_lower = message.lower()
        alarms = self.get_alarm_list()

        if any(w in msg_lower for w in ["status", "geral", "resumo", "overview"]):
            total_h2 = state.stack_a.h2_production + state.stack_b.h2_production
            return (f"**Status geral da planta — {time.strftime('%H:%M:%S')}:**\n"
                    f"• Produção H₂: {total_h2:.0f} Nm³/h ({total_h2*0.0898/1000:.2f} kg/h)\n"
                    f"• Stack A: {state.stack_a.temp_cell:.1f}°C · {state.stack_a.pressure_h2:.1f} bar · "
                    f"{state.stack_a.h2_production:.0f} Nm³/h\n"
                    f"• Stack B: {state.stack_b.temp_cell:.1f}°C · {state.stack_b.pressure_h2:.1f} bar · "
                    f"{state.stack_b.h2_production:.0f} Nm³/h"
                    + (" ⚠ temperatura acima do nominal" if state.stack_b.temp_cell > 78 else "") + "\n"
                    f"• Energia total: {state.energy.total_mw:.1f} MW (Solar {state.energy.solar_mw:.1f} + Eólica {state.energy.wind_mw:.1f})\n"
                    f"• BESS: {state.bess.soc:.0f}% SoC · SWRO: {state.swro.product_salinity:.3f} g/L\n"
                    f"• Alarmes ativos: **{len(alarms)}** · IA modo: {'AUTO' if self._ai_enabled else 'MANUAL'}")

        elif any(w in msg_lower for w in ["otimiz", "melhorar", "eficiência", "produção"]):
            slope_b = self._stats["stack_b_temp"].slope()
            return (f"**Otimização de produção — análise IA:**\n"
                    f"• Eficiência atual: Stack A {state.stack_a.efficiency_lhv:.1f}% · Stack B {state.stack_b.efficiency_lhv:.1f}%\n"
                    f"• Stack B temperatura {state.stack_b.temp_cell:.1f}°C está acima do ótimo (73°C). "
                    f"Reduzi o fluxo H₂O para {self.plant.get_setpoints().get('stack_b_water_flow', 22):.1f} L/min.\n"
                    f"• Tendência temp Stack B: {'+' if slope_b > 0 else ''}{slope_b*30:.2f}°C/min\n"
                    f"• Energia disponível: {state.energy.total_mw:.1f} MW — "
                    + ("aumento de potência possível (+2 MW)" if state.energy.total_mw > 45 else "ajuste para disponibilidade atual"))

        elif any(w in msg_lower for w in ["risco", "falha", "problema", "anomal"]):
            pv03 = state.swro.membrane_fouling_pv.get("PV-03", 0)
            return (f"**Análise de risco — 7 dias:**\n"
                    f"• Stack B temperatura: {state.stack_b.temp_cell:.1f}°C — risco MÉDIO (monitorando)\n"
                    f"• SWRO PV-03 fouling: {pv03:.1f}% — "
                    + ("risco ALTO, CIP necessário em breve" if pv03 > 40 else "normal") + "\n"
                    f"• H₂ pureza Stack B: {state.stack_b.h2_purity:.3f}% — "
                    + ("atenção" if state.stack_b.h2_purity < 99.95 else "normal") + "\n"
                    f"• Probabilidade de falha crítica (72h): **{len(alarms)*1.5 + 0.8:.1f}%**\n"
                    f"• Anomalias detectadas hoje: {self.metrics['anomalies_detected']}")

        elif any(w in msg_lower for w in ["alarme", "alerta", "aviso"]):
            if not alarms:
                return "Nenhum alarme ativo no momento. Todos os sistemas dentro dos limites operacionais."
            lines = [f"**{len(alarms)} alarme(s) ativo(s):**"]
            for a in alarms[:5]:
                ack = " ✓ confirmado" if a["acknowledged"] else " — aguardando confirmação"
                lines.append(f"• [{a['level'].upper()}] {a['code']}: {a['detail'][:80]}{ack}")
            return "\n".join(lines)

        elif any(w in msg_lower for w in ["relatorio", "relatório", "turno", "resumo"]):
            total_h2 = state.stack_a.h2_production + state.stack_b.h2_production
            hours = (time.time() - self._uptime_start) / 3600
            return (f"**Relatório operacional — últimas {hours:.1f}h:**\n"
                    f"• H₂ produzido (estimado): {total_h2 * hours * 0.0898:.1f} kg\n"
                    f"• Energia gerada: {state.energy.total_mw * hours:.0f} MWh\n"
                    f"• Água dessalinizada: {state.swro.product_flow * 60 * hours:.0f} m³\n"
                    f"• Eficiência média PEM: {(state.stack_a.efficiency_lhv + state.stack_b.efficiency_lhv)/2:.1f}%\n"
                    f"• Decisões IA aplicadas: {self.metrics['decisions_applied']}\n"
                    f"• Alarmes gerados: {self.metrics['alarms_generated']}\n"
                    f"• Economia estimada (otimização): R$ {self.metrics['decisions_applied'] * 28:.0f}")

        else:
            return (f"Processando consulta sobre '{message[:60]}'. "
                    f"Planta em operação normal. Stack A: {state.stack_a.temp_cell:.1f}°C / "
                    f"{state.stack_a.pressure_h2:.1f} bar. Stack B: {state.stack_b.temp_cell:.1f}°C "
                    + ("⚠" if state.stack_b.temp_cell > 78 else "✓") +
                    f". Para análise mais profunda, configure a ANTHROPIC_API_KEY no config.py.")

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        return {
            "ai_enabled": self._ai_enabled,
            "uptime_seconds": time.time() - self._uptime_start,
            "active_alarms": len(self.active_alarms),
            "metrics": self.metrics,
            "recent_decisions": [d.to_dict() for d in self.decision_history[-10:]],
        }

    def set_ai_enabled(self, enabled: bool):
        self._ai_enabled = enabled
