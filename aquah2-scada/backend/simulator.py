"""
AquaH2 AI-SCADA — Hardware Simulator
Replaces real MODBUS/OPC-UA/sensor reads for Phase 0 (software development).
In production, replace SimulatedPlant.read_sensors() with actual
pymodbus / pyopcua / serial calls.

Kraefegg M.O. · Developer: Railson
"""

import math
import time
import random
from dataclasses import dataclass, field, asdict
from typing import Dict, Any


# ── Data Models ──────────────────────────────────────────────────────

@dataclass
class ElectrolyzerStack:
    id: str
    enabled: bool = True
    power_pct: float = 85.0          # % of 25 MW
    water_flow_setpoint: float = 22.0  # L/min
    # Live readings (written by simulator)
    temp_cell: float = 72.0          # °C
    pressure_h2: float = 31.0        # bar differential
    current_dc: float = 4820.0       # A
    voltage_cell_avg: float = 1.89   # V
    water_flow_actual: float = 22.0  # L/min
    h2_production: float = 112.0     # Nm³/h
    h2_purity: float = 99.97         # %
    efficiency_lhv: float = 71.4     # %
    specific_energy: float = 4.82    # kWh/Nm³

@dataclass
class SwroUnit:
    enabled: bool = True
    capacity_pct: float = 65.0
    # Live
    feed_salinity: float = 35.2      # g/L
    product_salinity: float = 0.32   # g/L
    feed_pressure: float = 62.0      # bar
    brine_pressure: float = 60.8     # bar
    water_temp: float = 26.8         # °C
    product_flow: float = 3.47       # m³/min
    sdi: float = 2.8                 # Silt Density Index
    ph: float = 7.2
    conductivity: float = 640.0      # µS/cm
    turbidity: float = 0.08          # NTU
    recovery_rate: float = 40.0      # %
    specific_energy: float = 3.4     # kWh/m³
    membrane_fouling_pv: Dict[str, float] = field(default_factory=lambda: {
        "PV-01": 18.0, "PV-02": 22.0, "PV-03": 41.0,
        "PV-04": 15.0, "PV-05": 29.0, "PV-06": 19.0
    })

@dataclass
class EnergySystem:
    solar_mw: float = 18.4
    wind_mw: float = 20.1
    irradiance: float = 842.0        # W/m²
    wind_speed: float = 9.4          # m/s at hub height
    wind_direction: float = 22.0     # degrees
    solar_pr: float = 0.82           # Performance Ratio
    inverters_online: int = 48
    turbines_online: int = 10
    total_mw: float = 38.5

@dataclass
class BessUnit:
    enabled: bool = True
    soc: float = 82.0                # % State of Charge
    power_kw: float = 0.0            # + = charging, - = discharging
    temp_bank: float = 28.4          # °C
    cycles: int = 412
    soh: float = 96.2                # % State of Health
    energy_kwh: float = 16.4         # MWh stored

@dataclass
class H2Storage:
    tank_level_pct: float = 48.0     # %
    tank_mass_t: float = 2.4         # tonnes
    tank_pressure_bar: float = 874.0
    tank_temp: float = 22.1          # °C
    compressor_running: bool = True
    compressor_flow: float = 36.8    # Nm³/h

@dataclass
class Nh3System:
    running: bool = True
    reactor_temp: float = 425.0      # °C
    reactor_pressure: float = 180.0  # bar
    conversion_rate: float = 22.4    # %
    production_kgh: float = 118.0    # kg/h
    tank_level_pct: float = 41.0
    tank_mass_t: float = 246.0

@dataclass
class SafetySensors:
    h2_lel: Dict[str, float] = field(default_factory=lambda: {
        f"DET-H2-{i:02d}": random.uniform(0.04, 0.14) for i in range(1, 9)
    })
    nh3_ppm: Dict[str, float] = field(default_factory=lambda: {
        f"DET-NH3-{i:02d}": random.uniform(2.0, 14.0) for i in range(1, 7)
    })
    esd_armed: bool = True
    esd_triggered: bool = False
    psv_status: str = "CLOSED"

@dataclass
class NetworkNode:
    name: str
    node_type: str
    ip: str
    protocol: str
    latency_ms: float = 2.0
    online: bool = True
    last_seen: float = field(default_factory=time.time)

@dataclass
class PlantState:
    stack_a: ElectrolyzerStack = field(default_factory=lambda: ElectrolyzerStack("A"))
    stack_b: ElectrolyzerStack = field(default_factory=lambda: ElectrolyzerStack("B",
        power_pct=84.0, temp_cell=78.9, pressure_h2=34.8,
        current_dc=4710.0, voltage_cell_avg=1.91, water_flow_setpoint=22.0,
        h2_production=109.0, efficiency_lhv=70.8))
    swro: SwroUnit = field(default_factory=SwroUnit)
    energy: EnergySystem = field(default_factory=EnergySystem)
    bess: BessUnit = field(default_factory=BessUnit)
    h2_storage: H2Storage = field(default_factory=H2Storage)
    nh3: Nh3System = field(default_factory=Nh3System)
    safety: SafetySensors = field(default_factory=SafetySensors)
    timestamp: float = field(default_factory=time.time)


# ── Simulator Engine ──────────────────────────────────────────────────

class SimulatedPlant:
    """
    Simulates the full AquaH2 plant sensor readings.
    
    In production, replace _read_hardware() with actual driver calls:
        from pymodbus.client import ModbusTcpClient
        client = ModbusTcpClient('192.168.1.100', port=502)
        regs = client.read_holding_registers(0, 20, slave=1)
        temp = regs.registers[0] / 10.0
    
    Or with OPC-UA:
        from opcua import Client
        client = Client("opc.tcp://192.168.1.101:4840")
        node = client.get_node("ns=2;i=1001")
        temp = node.get_value()
    """

    def __init__(self):
        self.state = PlantState()
        self._t = 0.0
        self._setpoints: Dict[str, float] = {
            "stack_a_power_pct":  86.0,
            "stack_b_power_pct":  84.0,
            "stack_a_water_flow": 22.0,
            "stack_b_water_flow": 22.0,
            "h2_pressure_target": 32.0,
            "swro_capacity_pct":  65.0,
            "bess_priority_pct":  20.0,
        }
        self._toggles: Dict[str, bool] = {
            "stack_a": True,
            "stack_b": True,
            "swro": True,
            "bess": True,
            "nh3": True,
            "ai_mode": True,
        }
        self._fault_injection: Dict[str, bool] = {}
        self._network_nodes = self._init_network()

    # ── Network ───────────────────────────────────────────────────────

    def _init_network(self) -> Dict[str, NetworkNode]:
        nodes = {
            "ai-edge":    NetworkNode("AI Edge Server", "server",   "10.0.1.10", "OPC-UA+MQTT"),
            "scada":      NetworkNode("SCADA Server",   "server",   "10.0.1.11", "OPC-UA"),
            "sw-01":      NetworkNode("IND-SW-01",      "switch",   "10.0.2.1",  "GbE"),
            "sw-02":      NetworkNode("IND-SW-02",      "switch",   "10.0.2.2",  "GbE"),
            "sw-03":      NetworkNode("IND-SW-03",      "switch",   "10.0.2.3",  "GbE"),
            "wifi-ap-01": NetworkNode("WiFi-AP W-01",   "wifi",     "10.0.3.1",  "WiFi6"),
            "wifi-ap-02": NetworkNode("WiFi-AP W-02",   "wifi",     "10.0.3.2",  "WiFi6"),
            "wifi-ap-03": NetworkNode("WiFi-AP W-03",   "wifi",     "10.0.3.3",  "WiFi6", latency_ms=148.0),
            "plc-elec":   NetworkNode("PLC Eletrolisador","plc",    "10.0.4.10", "MODBUS TCP"),
            "plc-swro":   NetworkNode("PLC SWRO",       "plc",      "10.0.4.20", "EtherNet/IP"),
            "plc-energy": NetworkNode("PLC Energia",    "plc",      "10.0.4.30", "MODBUS TCP"),
            "plc-bess":   NetworkNode("PLC BESS",       "plc",      "10.0.4.40", "MODBUS TCP"),
        }
        return nodes

    # ── Signal generators ─────────────────────────────────────────────

    def _sin(self, freq: float, amp: float, phase: float = 0.0) -> float:
        return amp * math.sin(2 * math.pi * freq * self._t + phase)

    def _noise(self, amp: float) -> float:
        return amp * (random.random() - 0.5) * 2

    def _bounded(self, val: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, val))

    # ── Main simulation tick ──────────────────────────────────────────

    def tick(self) -> PlantState:
        """
        Advance simulation by one time step.
        In production: replace body with hardware reads.
        """
        self._t += 1.0
        s = self.state

        # ── Solar + Wind ──────────────────────────────────────────────
        # Solar follows a day cycle (assuming t in seconds, 86400s = day)
        hour = (self._t % 86400) / 3600
        solar_profile = max(0.0, math.sin(math.pi * (hour - 6) / 12))  # 06:00–18:00
        s.energy.irradiance = self._bounded(
            800.0 * solar_profile + self._sin(0.002, 80) + self._noise(40), 0, 1050)
        s.energy.solar_mw = self._bounded(
            25.0 * solar_profile * 0.82 + self._sin(0.003, 2.0) + self._noise(0.8),
            0, 25.0)

        s.energy.wind_speed = self._bounded(
            9.4 + self._sin(0.0008, 3.5) + self._sin(0.005, 1.2) + self._noise(0.4),
            3.0, 16.0)
        ws = s.energy.wind_speed
        # Wind power curve: cut-in 3m/s, rated 11.5m/s, cut-out 25m/s
        if ws < 3.0:
            wp = 0.0
        elif ws < 11.5:
            wp = 25.0 * ((ws - 3.0) / (11.5 - 3.0)) ** 3
        elif ws < 25.0:
            wp = 25.0
        else:
            wp = 0.0
        s.energy.wind_mw = self._bounded(wp + self._noise(0.5), 0, 25.0)
        s.energy.total_mw = s.energy.solar_mw + s.energy.wind_mw

        # ── BESS ──────────────────────────────────────────────────────
        if s.bess.enabled and self._toggles.get("bess", True):
            surplus = s.energy.total_mw - 47.0  # 47 MW = electrolyzer + aux
            bess_pct = self._setpoints["bess_priority_pct"] / 100.0
            s.bess.power_kw = self._bounded(surplus * bess_pct * 1000, -10000, 10000)
            s.bess.soc = self._bounded(
                s.bess.soc + s.bess.power_kw * 0.00002,  # 2s tick effect
                self._setpoints.get("bess_soc_min", 5), 95)
            s.bess.energy_kwh = s.bess.soc / 100.0 * 20.0  # 20 MWh capacity
            s.bess.temp_bank = self._bounded(
                28.4 + abs(s.bess.power_kw) * 0.0003 + self._noise(0.2), 20, 50)

        # ── Electrolyzer Stack A ──────────────────────────────────────
        self._sim_stack(s.stack_a, "stack_a", base_temp=72.3, base_press=31.2)

        # ── Electrolyzer Stack B (slightly hotter — fault scenario) ───
        self._sim_stack(s.stack_b, "stack_b", base_temp=78.9, base_press=34.8)

        # ── SWRO ──────────────────────────────────────────────────────
        if s.swro.enabled and self._toggles.get("swro", True):
            cap = self._setpoints["swro_capacity_pct"] / 100.0
            s.swro.feed_pressure = self._bounded(
                62.0 + self._sin(0.004, 2.5) + self._noise(0.5), 55, 70)
            s.swro.product_flow = self._bounded(
                3.47 * cap + self._sin(0.003, 0.3) + self._noise(0.1), 0, 5.8)
            s.swro.product_salinity = self._bounded(
                0.32 + self._sin(0.002, 0.04) + self._noise(0.02), 0.05, 0.60)
            s.swro.water_temp = self._bounded(
                26.8 + self._sin(0.001, 1.2) + self._noise(0.2), 20, 35)
            s.swro.sdi = self._bounded(
                2.8 + self._sin(0.001, 0.3) + self._noise(0.1), 0.5, 4.0)
            # Slow membrane fouling progression
            for pv in s.swro.membrane_fouling_pv:
                s.swro.membrane_fouling_pv[pv] = min(100.0,
                    s.swro.membrane_fouling_pv[pv] + random.uniform(0, 0.001))

        # ── H2 Storage & NH3 ─────────────────────────────────────────
        total_h2 = (s.stack_a.h2_production if s.stack_a.enabled else 0) + \
                   (s.stack_b.h2_production if s.stack_b.enabled else 0)
        nh3_h2_consumption = s.nh3.production_kgh / 0.178 * 0.001  # Nm³/h consumed
        net_h2_nm3 = total_h2 - nh3_h2_consumption

        s.h2_storage.tank_level_pct = self._bounded(
            s.h2_storage.tank_level_pct + net_h2_nm3 * 0.0000004,
            0, 100)
        s.h2_storage.tank_mass_t = s.h2_storage.tank_level_pct / 100.0 * 5.0
        s.h2_storage.tank_pressure_bar = self._bounded(
            874.0 + self._sin(0.003, 15) + self._noise(5), 50, 900)
        s.h2_storage.tank_temp = self._bounded(
            22.1 + self._noise(0.3), 15, 35)

        if s.nh3.running and self._toggles.get("nh3", True):
            s.nh3.production_kgh = self._bounded(
                118.0 + self._sin(0.003, 6) + self._noise(2), 0, 150)
            s.nh3.reactor_temp = self._bounded(
                425.0 + self._sin(0.002, 12) + self._noise(3), 380, 500)
            s.nh3.reactor_pressure = self._bounded(
                180.0 + self._sin(0.002, 8) + self._noise(2), 140, 220)
            s.nh3.tank_level_pct = self._bounded(
                s.nh3.tank_level_pct + s.nh3.production_kgh * 0.0000003,
                0, 100)
            s.nh3.tank_mass_t = s.nh3.tank_level_pct / 100.0 * 600.0

        # ── Safety sensors ────────────────────────────────────────────
        for k in s.safety.h2_lel:
            s.safety.h2_lel[k] = self._bounded(
                s.safety.h2_lel.get(k, 0.1) + self._noise(0.03), 0, 100)
        for k in s.safety.nh3_ppm:
            s.safety.nh3_ppm[k] = self._bounded(
                s.safety.nh3_ppm.get(k, 8.0) + self._noise(0.5), 0, 150)

        # ── Network latency variation ─────────────────────────────────
        for key, node in self._network_nodes.items():
            if key == "wifi-ap-03":
                node.latency_ms = self._bounded(
                    148.0 + self._sin(0.01, 30) + self._noise(15), 80, 250)
            else:
                base = {"wifi-ap-01": 12, "wifi-ap-02": 14}.get(key, 2)
                node.latency_ms = self._bounded(
                    base + self._noise(0.8), 0.5, 20)
            node.last_seen = time.time()

        s.timestamp = time.time()
        return s

    def _sim_stack(self, stack: ElectrolyzerStack, name: str,
                   base_temp: float, base_press: float):
        """Simulate one PEM electrolyzer stack."""
        if not stack.enabled or not self._toggles.get(name, True):
            stack.h2_production = 0.0
            stack.current_dc = 0.0
            return

        pwr = self._setpoints[f"{name}_power_pct"] / 100.0
        sp_flow = self._setpoints[f"{name}_water_flow"]

        stack.water_flow_actual = self._bounded(
            sp_flow + self._sin(0.005, 1.2) + self._noise(0.3),
            0, 40)

        # Temperature depends on power and cooling (water flow)
        cooling = stack.water_flow_actual / 22.0
        stack.temp_cell = self._bounded(
            base_temp + (pwr - 0.85) * 12 - (cooling - 1.0) * 5
            + self._sin(0.004, 1.8) + self._noise(0.4),
            55, 92)

        stack.pressure_h2 = self._bounded(
            base_press + (pwr - 0.85) * 4
            + self._sin(0.005, 2.0) + self._noise(0.5),
            25, 42)

        stack.current_dc = self._bounded(
            pwr * 5500 + self._sin(0.005, 180) + self._noise(50),
            0, 6500)

        # Efficiency degrades slightly with temperature
        temp_penalty = max(0, (stack.temp_cell - 75) * 0.15)
        stack.efficiency_lhv = self._bounded(
            71.4 * pwr - temp_penalty + self._sin(0.003, 0.8) + self._noise(0.2),
            60, 80)

        stack.h2_production = self._bounded(
            (stack.efficiency_lhv / 100) * pwr * 25000 / 3.54
            + self._sin(0.004, 4) + self._noise(1.5),
            0, 150)

        stack.specific_energy = self._bounded(
            4.82 + (1 - stack.efficiency_lhv / 71.4) * 0.5 + self._noise(0.05),
            4.0, 6.5)

        stack.h2_purity = self._bounded(
            99.97 - (stack.temp_cell - 72) * 0.002 + self._noise(0.01),
            99.0, 100.0)

        stack.voltage_cell_avg = self._bounded(
            1.89 + (stack.temp_cell - 72) * 0.002 + self._noise(0.01),
            1.7, 2.2)

    # ── Setpoint / Command interface ──────────────────────────────────

    def apply_setpoint(self, key: str, value: float) -> bool:
        """Apply a setpoint change. In production: write to PLC register."""
        if key in self._setpoints:
            self._setpoints[key] = float(value)
            return True
        return False

    def apply_toggle(self, key: str, value: bool) -> bool:
        """Toggle a system. In production: send digital output command to PLC."""
        if key in self._toggles:
            self._toggles[key] = bool(value)
            if key == "stack_a":
                self.state.stack_a.enabled = value
            elif key == "stack_b":
                self.state.stack_b.enabled = value
            elif key == "swro":
                self.state.swro.enabled = value
            elif key == "bess":
                self.state.bess.enabled = value
            return True
        return False

    def trigger_esd(self) -> str:
        """Emergency Shutdown. In production: activate ESD relay output."""
        self.state.safety.esd_triggered = True
        self.state.safety.esd_armed = False
        self._toggles["stack_a"] = False
        self._toggles["stack_b"] = False
        self._toggles["nh3"] = False
        self.state.stack_a.enabled = False
        self.state.stack_b.enabled = False
        self.state.nh3.running = False
        return "ESD ATIVADO: Eletrolisador e síntese NH3 desligados. Aguardando reset do supervisor."

    def reset_esd(self) -> str:
        """Reset ESD after incident. In production: hardware interlock key."""
        self.state.safety.esd_triggered = False
        self.state.safety.esd_armed = True
        self._toggles["stack_a"] = True
        self._toggles["stack_b"] = True
        self._toggles["nh3"] = True
        self.state.stack_a.enabled = True
        self.state.stack_b.enabled = True
        self.state.nh3.running = True
        return "ESD resetado. Sistemas em sequência de partida normal."

    def get_setpoints(self) -> Dict[str, Any]:
        return {**self._setpoints}

    def get_toggles(self) -> Dict[str, bool]:
        return {**self._toggles}

    def get_network_status(self) -> Dict[str, Any]:
        return {k: {
            "name": n.name, "type": n.node_type, "ip": n.ip,
            "protocol": n.protocol, "latency_ms": round(n.latency_ms, 1),
            "online": n.online, "last_seen": n.last_seen
        } for k, n in self._network_nodes.items()}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full plant state to JSON-compatible dict."""
        s = self.state
        return {
            "timestamp": s.timestamp,
            "stack_a": asdict(s.stack_a),
            "stack_b": asdict(s.stack_b),
            "swro": asdict(s.swro),
            "energy": asdict(s.energy),
            "bess": asdict(s.bess),
            "h2_storage": asdict(s.h2_storage),
            "nh3": asdict(s.nh3),
            "safety": {
                "h2_lel": s.safety.h2_lel,
                "nh3_ppm": s.safety.nh3_ppm,
                "esd_armed": s.safety.esd_armed,
                "esd_triggered": s.safety.esd_triggered,
                "psv_status": s.safety.psv_status,
            },
            "setpoints": self.get_setpoints(),
            "toggles": self.get_toggles(),
            "network": self.get_network_status(),
        }
