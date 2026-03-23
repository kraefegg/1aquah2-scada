# AquaH₂ AI-SCADA — Referência da API

## Base URL

```
http://localhost:8765
```

Todos os endpoints retornam `application/json` com CORS aberto (`Access-Control-Allow-Origin: *`).

---

## Endpoints GET

### `GET /api/state`
Estado completo da planta em tempo real.

**Resposta:**
```json
{
  "timestamp": 1711234567.89,
  "stack_a": {
    "enabled": true,
    "temp": 72.3,
    "pressure": 31.2,
    "current": 4820.0,
    "voltage": 1.89,
    "flow": 22.1,
    "h2_nm3h": 112.0,
    "h2_purity": 99.97,
    "efficiency": 71.4,
    "spec_energy": 4.82
  },
  "stack_b": { "...": "..." },
  "energy": {
    "solar_mw": 18.4,
    "wind_mw": 20.1,
    "irradiance": 842.0,
    "wind_speed": 9.4,
    "total_mw": 38.5
  },
  "bess": { "soc": 82.0, "power_kw": 0.0, "temp": 28.4 },
  "swro": { "feed_pressure": 62.0, "product_salinity": 0.32, "product_flow": 3.47 },
  "h2_storage": { "level_pct": 48.0, "mass_t": 2.4, "pressure_bar": 874.0 },
  "nh3": { "prod_kgh": 118.0, "reactor_temp": 425.0, "tank_pct": 41.0 },
  "safety": {
    "h2_lel": { "DET-H2-01": 0.08, "...": "..." },
    "nh3_ppm": { "DET-NH3-01": 12.0, "...": "..." },
    "esd_armed": true
  }
}
```

---

### `GET /api/history/{tag}`

Série temporal de um sensor.

**Parâmetros de query:**
- `hours` (float, default: 24) — janela de tempo em horas
- `limit` (int, default: 500) — máximo de pontos

**Tags disponíveis:**

| Tag | Unidade | Descrição |
|-----|---------|-----------|
| `stack_a_temp` | °C | Temperatura Stack A |
| `stack_b_temp` | °C | Temperatura Stack B |
| `stack_a_pressure` | bar | Pressão H₂ Stack A |
| `stack_b_pressure` | bar | Pressão H₂ Stack B |
| `stack_a_h2` | Nm³/h | Produção H₂ Stack A |
| `stack_b_h2` | Nm³/h | Produção H₂ Stack B |
| `stack_a_efficiency` | % LHV | Eficiência Stack A |
| `stack_b_efficiency` | % LHV | Eficiência Stack B |
| `solar_mw` | MW | Geração solar |
| `wind_mw` | MW | Geração eólica |
| `total_mw` | MW | Potência total |
| `bess_soc` | % | Estado de carga BESS |
| `swro_salinity` | g/L | Salinidade produto |
| `swro_flow` | m³/min | Vazão produto |
| `nh3_rate` | kg/h | Produção NH₃ |

**Exemplo:**
```bash
curl "http://localhost:8765/api/history/stack_a_temp?hours=6"
```

**Resposta:**
```json
{
  "tag": "stack_a_temp",
  "data": [
    { "ts": 1711234500.0, "value": 72.1 },
    { "ts": 1711234510.0, "value": 72.3 }
  ]
}
```

---

### `GET /api/alarms`

Alarmes ativos e histórico.

```json
{
  "active": [
    {
      "code": "ALM-0004",
      "level": "warn",
      "message": "Stack B — temperatura aviso",
      "ts": 1711234567.0,
      "acked": false,
      "ack_by": ""
    }
  ],
  "history": [ "..." ]
}
```

---

### `GET /api/events?limit=80`

Log completo de eventos, alarmes e decisões IA.

---

### `GET /api/ai/status`

Métricas do motor de IA.

```json
{
  "decisions": 142,
  "alarms": 8,
  "anomalies": 3,
  "uptime_start": 1711230000.0
}
```

---

## Endpoints POST

### `POST /api/setpoint`

Altera um setpoint da planta.

**Body:**
```json
{ "tag": "stack_b_flow", "value": 21.5 }
```

**Setpoints disponíveis:**

| Tag | Faixa | Descrição |
|-----|-------|-----------|
| `stack_a_power` | 30–100 | % potência Stack A |
| `stack_b_power` | 30–100 | % potência Stack B |
| `stack_a_flow` | 10–40 | Fluxo H₂O A (L/min) |
| `stack_b_flow` | 10–40 | Fluxo H₂O B (L/min) |
| `h2_pressure` | 20–35 | Pressão alvo H₂ (bar) |
| `swro_capacity` | 20–100 | % capacidade SWRO |
| `bess_priority` | 0–50 | % prioridade BESS |

---

### `POST /api/toggle`

Liga ou desliga um subsistema.

```json
{ "key": "stack_b", "value": false }
```

**Keys disponíveis:** `stack_a`, `stack_b`, `swro`, `bess`, `nh3`, `ai_mode`

---

### `POST /api/chat`

Envia mensagem ao assistente IA.

```json
{ "message": "status da planta" }
```

**Resposta:**
```json
{ "response": "**Status — 14:32:18**\n• H₂: 221 Nm³/h...", "ts": 1711234567.0 }
```

---

### `POST /api/esd`

Aciona parada de emergência (ESD).

```json
{}
```

**Resposta:**
```json
{ "status": "triggered", "message": "ESD ATIVADO — Eletrolisadores e síntese NH3 desligados." }
```

---

### `POST /api/esd/reset`

Reset do ESD após incidente.

---

### `POST /api/alarms/ack`

Confirmar alarme.

```json
{ "code": "ALM-0004", "operator": "railson" }
```

---

## WebSocket

**Endpoint:** `ws://localhost:8765/ws`

### Mensagens do cliente → servidor

```json
{ "cmd": "setpoint",  "data": { "tag": "stack_b_flow", "value": 21.0 } }
{ "cmd": "toggle",    "data": { "key": "bess", "value": true } }
{ "cmd": "chat",      "data": { "message": "otimize a produção" } }
{ "cmd": "esd",       "data": {} }
{ "cmd": "esd_reset", "data": {} }
{ "cmd": "ack_alarm", "data": { "code": "ALM-0004", "operator": "railson" } }
{ "cmd": "ping",      "data": {} }
```

### Mensagens do servidor → cliente

```json
{ "type": "state",         "data": { ...plant_state... } }
{ "type": "ai_decision",   "data": { "action_type": "setpoint", "reason": "...", "conf": 0.85 } }
{ "type": "alarms",        "data": [ {...} ] }
{ "type": "chat_response", "message": "texto da resposta..." }
{ "type": "esd",           "status": "triggered", "message": "..." }
{ "type": "ack",           "ok": true }
{ "type": "pong" }
```

---

## Códigos de alarme

| Código | Nível | Descrição |
|--------|-------|-----------|
| ALM-0001 | WARN | Stack A temperatura aviso (>80°C) |
| ALM-0002 | ALARM | Stack A temperatura alarme (>82°C) |
| ALM-0003 | TRIP | Stack A temperatura crítica (>85°C) — ESD |
| ALM-0004 | WARN | Stack B temperatura aviso |
| ALM-0005 | ALARM | Stack B temperatura alarme |
| ALM-0006 | TRIP | Stack B temperatura crítica — ESD |
| ALM-0010 | WARN | Stack A pressão H₂ alta (>35 bar) |
| ALM-0011 | TRIP | Stack A pressão H₂ crítica (>40 bar) — ESD |
| ALM-0012 | WARN | Stack B pressão H₂ alta |
| ALM-0013 | TRIP | Stack B pressão H₂ crítica — ESD |
| ALM-0020 | WARN | H₂ LEL detectado (>25%) |
| ALM-0021 | TRIP | H₂ LEL crítico (>50%) — ESD |
| ALM-0030 | WARN | NH₃ acima TLV-TWA (>25 ppm) |
| ALM-0031 | TRIP | NH₃ crítico (>100 ppm) — ESD |
| ALM-0041 | WARN | SWRO salinidade produto alta (>0.5 g/L) |
| ALM-0050 | WARN | BESS SoC baixo (<20%) |
