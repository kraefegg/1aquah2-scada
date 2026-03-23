# Conectar Hardware Real

O ponto de integração é o método `Plant.tick()` no arquivo `run.py`.  
Em modo simulado ele calcula a física. Em produção, substitua pelo driver do seu hardware.  
**Nada mais no sistema precisa ser alterado.**

---

## Protocolo MODBUS TCP

Compatível com: Siemens S7-300/400/1200/1500, Allen-Bradley, ABB, Schneider, Mitsubishi, qualquer CLP com MODBUS TCP.

```bash
pip install pymodbus>=3.6.0
```

```python
from pymodbus.client import ModbusTcpClient

# No __init__ da classe Plant:
self._plc = ModbusTcpClient('192.168.1.100', port=502)
self._plc.connect()

# No método tick():
def tick(self):
    regs_a = self._plc.read_holding_registers(address=0, count=10, slave=1)
    if not regs_a.isError():
        self._state['stack_a']['temp']        = regs_a.registers[0] / 10.0
        self._state['stack_a']['pressure']    = regs_a.registers[1] / 10.0
        self._state['stack_a']['current']     = regs_a.registers[2] * 1.0
        self._state['stack_a']['h2_nm3h']     = regs_a.registers[3] / 10.0
        self._state['stack_a']['efficiency']  = regs_a.registers[4] / 10.0

    # Para escrever setpoints no PLC:
    def apply_setpoint(self, key, value):
        if key == 'stack_a_flow':
            self._plc.write_register(address=100, value=int(value * 10), slave=1)
```

### Tabela de mapeamento sugerida

| Reg Holding | Endereço Siemens | Escala | Tag |
|-------------|-----------------|--------|-----|
| 0 | MW 100 | ÷10 | stack_a_temp (°C) |
| 1 | MW 102 | ÷10 | stack_a_pressure (bar) |
| 2 | MW 104 | ×1 | stack_a_current (A) |
| 3 | MW 106 | ÷10 | stack_a_h2_nm3h (Nm³/h) |
| 10 | MW 120 | ÷10 | stack_b_temp (°C) |
| 20 | MW 140 | ÷10 | solar_mw (MW) |
| 21 | MW 142 | ÷10 | wind_mw (MW) |
| 30 | MW 160 | ÷10 | swro_pressure (bar) |
| 31 | MW 162 | ÷1000 | swro_salinity (g/L) |

---

## Protocolo MODBUS RTU / RS-485

Para sensores de campo com interface serial.

```python
from pymodbus.client import ModbusSerialClient

client = ModbusSerialClient(
    method='rtu',
    port='/dev/ttyUSB0',   # Linux/Mac
    # port='COM3',         # Windows
    baudrate=9600,
    parity='N',
    stopbits=1,
    bytesize=8,
    timeout=1
)
client.connect()
```

---

## Protocolo OPC-UA

Compatível com: Siemens TIA Portal (S7-1500 com OPC-UA ativo), Beckhoff TwinCAT, CODESYS, Kepware.

```bash
pip install opcua>=0.98.0
```

```python
from opcua import Client

client = Client("opc.tcp://192.168.1.101:4840")
client.set_security_string("Basic256Sha256,SignAndEncrypt,cert.pem,key.pem")
client.connect()

# Ler valor
node_temp_a = client.get_node("ns=2;i=1001")  # Node ID do sensor
self._state['stack_a']['temp'] = node_temp_a.get_value()

# Escrever setpoint
node_flow_a = client.get_node("ns=2;i=2001")
node_flow_a.set_value(float(value))
```

---

## Protocolo MQTT (ESP32, Raspberry Pi, LoRaWAN)

```bash
pip install paho-mqtt>=1.6.1
```

### Publicar dados do ESP32

```cpp
// Firmware ESP32 (Arduino)
#include <PubSubClient.h>

void publishSensors() {
  char payload[64];
  snprintf(payload, sizeof(payload), "{\"value\": %.1f}", readTemperature());
  client.publish("aquah2/stack_a/temp", payload);
}
```

### Receber no servidor Python

```python
import paho.mqtt.client as mqtt

def on_message(client, userdata, msg):
    data = json.loads(msg.payload.decode())
    topic = msg.topic
    
    mapping = {
        "aquah2/stack_a/temp":     ("stack_a", "temp"),
        "aquah2/stack_a/pressure": ("stack_a", "pressure"),
        "aquah2/stack_b/temp":     ("stack_b", "temp"),
        "aquah2/solar/power":      ("energy",  "solar_mw"),
        "aquah2/wind/power":       ("energy",  "wind_mw"),
        "aquah2/swro/salinity":    ("swro",    "product_salinity"),
    }
    
    if topic in mapping:
        subsystem, field = mapping[topic]
        plant._state[subsystem][field] = float(data["value"])

mqtt_client = mqtt.Client()
mqtt_client.on_message = on_message
mqtt_client.connect("localhost", 1883)
mqtt_client.subscribe("aquah2/#")
mqtt_client.loop_start()
```

---

## Raspberry Pi + Sensores Analógicos

Para sensores 4–20 mA ou 0–10V via ADC (ADS1115, MCP3208):

```bash
pip install adafruit-circuitpython-ads1x15
```

```python
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)
channel = AnalogIn(ads, ADS.P0)

# 4-20 mA → temperatura (ex: PT100 transmissor 0-100°C)
def read_4_20ma_temp():
    current_ma = (channel.voltage / 250.0) * 1000  # R_shunt = 250Ω
    temp = (current_ma - 4.0) / 16.0 * 100.0       # 4mA=0°C, 20mA=100°C
    return temp

self._state['stack_a']['temp'] = read_4_20ma_temp()
```

---

## Checklist de integração de hardware

- [ ] Testar comunicação com o hardware em script isolado antes de integrar
- [ ] Definir endereços MODBUS / Node IDs OPC-UA para cada sensor
- [ ] Configurar tabela de escala (raw → unidade de engenharia) para cada sensor
- [ ] Adicionar tratamento de erro (timeout, disconnect) no método tick()
- [ ] Ajustar os limites de engenharia em LIMITS (config.py ou run.py) para os valores reais
- [ ] Testar o ESD automático em bancada antes de conectar em planta real
- [ ] Verificar que a taxa de atualização (2s padrão) é compatível com o hardware
