"""
AquaH2 AI-SCADA Platform — Configuration
Kraefegg M.O. · Developer: Railson
"""

# ── Server ──────────────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 8765
WEBSOCKET_PATH = "/ws"
API_PREFIX = "/api/v1"
CORS_ORIGINS = ["*"]   # Restrict to specific origins in production

# ── Database ─────────────────────────────────────────────────────────
DB_PATH = "aquah2_data.db"
HISTORY_RETENTION_HOURS = 72    # Keep 72h of 2-second samples in DB
HISTORY_TRIM_INTERVAL_S = 3600  # Trim old data every hour

# ── Simulator ────────────────────────────────────────────────────────
SIM_TICK_INTERVAL_S = 2.0       # How often sensors update (seconds)

# ── AI Engine ────────────────────────────────────────────────────────
AI_DECISION_INTERVAL_S = 10.0   # How often AI runs its control loop
AI_TREND_WINDOW = 30            # Number of samples for trend analysis
ANOMALY_ZSCORE_THRESHOLD = 2.8  # Standard deviations → anomaly

# ── Anthropic (optional LLM for chat) ────────────────────────────────
# Set your API key here or via ANTHROPIC_API_KEY env variable
ANTHROPIC_API_KEY = ""          # Leave empty to use built-in responses
ANTHROPIC_MODEL   = "claude-sonnet-4-6"

# ── Plant Physical Limits ─────────────────────────────────────────────
LIMITS = {
    # Electrolyzer Stack A & B
    "stack_temp_nominal":  (60.0, 80.0),   # °C  (lo, hi)
    "stack_temp_alarm":    (55.0, 82.0),
    "stack_temp_trip":     (50.0, 85.0),
    "stack_pressure_nominal": (28.0, 35.0),  # bar
    "stack_pressure_alarm":   (25.0, 37.0),
    "stack_pressure_trip":    (20.0, 40.0),
    "stack_current_max":   6000.0,          # A
    "h2_purity_min":       99.90,           # %
    "h2_purity_alarm":     99.50,

    # SWRO
    "swro_pressure_nominal": (55.0, 70.0),  # bar
    "swro_salinity_max":     0.50,          # g/L product
    "swro_sdi_max":          3.0,
    "swro_ph_nominal":       (6.5, 8.5),

    # H2 Storage
    "h2_tank_pressure_max": 900.0,          # bar
    "h2_lel_alarm":         25.0,           # % LEL
    "h2_lel_trip":          50.0,           # % LEL

    # NH3
    "nh3_ppm_alarm":        25.0,           # ppm TLV-TWA
    "nh3_ppm_trip":         100.0,

    # BESS
    "bess_soc_min":         20.0,           # %
    "bess_soc_max":         95.0,
    "bess_temp_max":        45.0,           # °C

    # Energy
    "plant_capacity_mw":    50.0,
}

# ── Setpoint Defaults ────────────────────────────────────────────────
SETPOINTS = {
    "stack_a_power_pct":    86.0,   # % of 25 MW
    "stack_b_power_pct":    84.0,
    "stack_a_water_flow":   22.0,   # L/min
    "stack_b_water_flow":   22.0,
    "h2_pressure_target":   32.0,   # bar
    "swro_capacity_pct":    65.0,   # %
    "bess_priority_pct":    20.0,   # % of surplus power to BESS
}

# ── Alarm Codes ──────────────────────────────────────────────────────
ALARM_CODES = {
    "ALM-0001": "Stack A — Temperatura acima do limite de aviso",
    "ALM-0002": "Stack A — Temperatura acima do limite de alarme",
    "ALM-0003": "ALM-TRIP Stack A — Temperatura crítica — ESD ativado",
    "ALM-0004": "Stack B — Temperatura acima do limite de aviso",
    "ALM-0005": "Stack B — Temperatura acima do limite de alarme",
    "ALM-0006": "ALM-TRIP Stack B — Temperatura crítica — ESD ativado",
    "ALM-0010": "Stack A — Pressão H2 acima do limite de aviso",
    "ALM-0011": "ALM-TRIP Stack A — Pressão H2 crítica — ESD ativado",
    "ALM-0012": "Stack B — Pressão H2 acima do limite de aviso",
    "ALM-0013": "ALM-TRIP Stack B — Pressão H2 crítica — ESD ativado",
    "ALM-0020": "H2 LEL — Concentração de H2 detectada (>25% LEL)",
    "ALM-0021": "ALM-TRIP H2 LEL — Concentração crítica (>50% LEL) — ESD ativado",
    "ALM-0030": "NH3 — Concentração acima do TLV-TWA (25 ppm)",
    "ALM-0031": "ALM-TRIP NH3 — Concentração crítica (>100 ppm) — ESD ativado",
    "ALM-0040": "SWRO — Pressão de membrana fora da faixa nominal",
    "ALM-0041": "SWRO — Salinidade do produto acima de 0.5 g/L",
    "ALM-0050": "BESS — SoC abaixo do mínimo (20%)",
    "ALM-0051": "BESS — Temperatura do banco elevada",
    "NET-0001": "Rede — Nó offline ou latência acima do limite",
    "AI-0001":  "IA — Anomalia detectada em série temporal",
    "AI-0002":  "IA — Manutenção preditiva recomendada",
}
