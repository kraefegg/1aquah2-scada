"""
AquaH2 AI-SCADA — Main Server (FastAPI + WebSocket)
Entry point. Run with: python main.py

Architecture:
  - WebSocket /ws           → real-time bidirectional (sensors + commands)
  - GET  /api/v1/state      → full plant snapshot (JSON)
  - GET  /api/v1/history    → time-series data from DB
  - POST /api/v1/setpoint   → apply setpoint change
  - POST /api/v1/toggle     → enable/disable subsystem
  - POST /api/v1/chat       → AI chat message
  - POST /api/v1/esd        → emergency shutdown
  - POST /api/v1/esd/reset  → reset ESD
  - GET  /api/v1/alarms     → active alarms
  - POST /api/v1/alarms/ack → acknowledge alarm
  - GET  /api/v1/events     → event log
  - GET  /api/v1/ai/status  → AI engine metrics
  - GET  /                  → serve SCADA frontend HTML

Kraefegg M.O. · Developer: Railson
"""

import asyncio
import json
import time
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import threading
import socket
import traceback
from typing import Set, Dict, Any

from simulator import SimulatedPlant
from ai_engine import AquaH2AIEngine
from database import Database
from config import HOST, PORT, SIM_TICK_INTERVAL_S, AI_DECISION_INTERVAL_S, HISTORY_TRIM_INTERVAL_S

# ── Try to use fastapi/uvicorn if available, else fall back to stdlib ──
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    USE_FASTAPI = True
except ImportError:
    USE_FASTAPI = False


# ── Globals ────────────────────────────────────────────────────────────

plant   = SimulatedPlant()
ai      = AquaH2AIEngine(plant)
db      = Database()
clients: Set = set()   # WebSocket clients

FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "..", "aquah2_platform.html")
if not os.path.exists(FRONTEND_PATH):
    FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "aquah2_platform.html")


# ══════════════════════════════════════════════════════════════════════
# FASTAPI IMPLEMENTATION
# ══════════════════════════════════════════════════════════════════════

if USE_FASTAPI:

    app = FastAPI(
        title="AquaH2 AI-SCADA",
        description="Kraefegg M.O. · Green Hydrogen + Desalination Control Platform",
        version="2.1.4"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Background tasks ──────────────────────────────────────────────

    async def sensor_loop():
        """Tick simulator and broadcast to all WebSocket clients."""
        trim_counter = 0
        while True:
            try:
                state = plant.tick()
                data = plant.to_dict()

                # Persist to DB every 5 ticks (~10s)
                trim_counter += 1
                if trim_counter % 5 == 0:
                    db.record_sensors(data)
                if trim_counter % (HISTORY_TRIM_INTERVAL_S // int(SIM_TICK_INTERVAL_S)) == 0:
                    db.trim_old_data()

                # Ingest into AI engine
                ai.ingest(state)

                # Broadcast to all connected WebSocket clients
                msg = json.dumps({"type": "state", "data": data})
                dead = set()
                for ws in clients:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.add(ws)
                clients.difference_update(dead)

            except Exception as e:
                print(f"[Sensor Loop] Error: {e}")

            await asyncio.sleep(SIM_TICK_INTERVAL_S)

    async def on_ai_decision(decision):
        """Broadcast AI decisions to clients and log them."""
        db.record_event("ai", decision.action_type,
                        decision.reason, f"target={decision.target} value={decision.value}")
        msg = json.dumps({"type": "ai_decision", "data": decision.to_dict()})
        dead = set()
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        clients.difference_update(dead)

    async def alarm_broadcast_loop():
        """Broadcast alarm list changes every 5 seconds."""
        prev_count = 0
        while True:
            curr = ai.get_alarm_list()
            if len(curr) != prev_count:
                prev_count = len(curr)
                msg = json.dumps({"type": "alarms", "data": curr})
                dead = set()
                for ws in clients:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.add(ws)
                clients.difference_update(dead)
            await asyncio.sleep(5.0)

    @app.on_event("startup")
    async def startup():
        asyncio.create_task(sensor_loop())
        asyncio.create_task(ai.run_control_loop(on_ai_decision))
        asyncio.create_task(alarm_broadcast_loop())
        print(f"\n{'='*60}")
        print(f"  AquaH2 AI-SCADA Platform — Kraefegg M.O.")
        print(f"  Developer: Railson")
        print(f"  Server: http://{HOST}:{PORT}")
        print(f"  Frontend: http://localhost:{PORT}/")
        print(f"  API docs: http://localhost:{PORT}/docs")
        print(f"  WebSocket: ws://localhost:{PORT}/ws")
        print(f"{'='*60}\n")

    # ── WebSocket ─────────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        clients.add(websocket)
        print(f"[WS] Client connected. Total: {len(clients)}")

        # Send initial full state immediately
        await websocket.send_text(json.dumps({
            "type": "state",
            "data": plant.to_dict()
        }))
        await websocket.send_text(json.dumps({
            "type": "alarms",
            "data": ai.get_alarm_list()
        }))

        try:
            while True:
                raw = await websocket.receive_text()
                await handle_ws_message(websocket, raw)
        except WebSocketDisconnect:
            clients.discard(websocket)
            print(f"[WS] Client disconnected. Total: {len(clients)}")
        except Exception as e:
            clients.discard(websocket)
            print(f"[WS] Error: {e}")

    async def handle_ws_message(ws: WebSocket, raw: str):
        """Process incoming WebSocket command from front-end."""
        try:
            msg = json.loads(raw)
            cmd = msg.get("cmd", "")
            payload = msg.get("data", {})

            if cmd == "setpoint":
                tag = payload.get("tag")
                val = float(payload.get("value", 0))
                old = plant.get_setpoints().get(tag, 0)
                ok = plant.apply_setpoint(tag, val)
                if ok:
                    db.record_setpoint(tag, old, val, "operator")
                    db.record_event("info", "SETPOINT", f"Setpoint alterado: {tag}", f"{old} → {val}")
                await ws.send_text(json.dumps({
                    "type": "ack", "cmd": cmd,
                    "ok": ok, "tag": tag, "value": val
                }))

            elif cmd == "toggle":
                key = payload.get("key")
                val = bool(payload.get("value", True))
                ok = plant.apply_toggle(key, val)
                db.record_event("info", "TOGGLE", f"Toggle: {key} = {val}", "")
                await ws.send_text(json.dumps({
                    "type": "ack", "cmd": cmd, "ok": ok, "key": key, "value": val
                }))

            elif cmd == "chat":
                message = payload.get("message", "")
                if message:
                    db.record_event("info", "CHAT", f"User: {message[:100]}", "")
                    response = await ai.chat(message)
                    await ws.send_text(json.dumps({
                        "type": "chat_response",
                        "message": response,
                        "ts": time.time()
                    }))

            elif cmd == "ack_alarm":
                code = payload.get("code", "")
                operator = payload.get("operator", "operator")
                ok = ai.acknowledge_alarm(code, operator)
                await ws.send_text(json.dumps({
                    "type": "ack", "cmd": cmd, "ok": ok, "code": code
                }))

            elif cmd == "esd":
                msg_esd = plant.trigger_esd()
                db.record_event("trip", "ESD", "PARADA DE EMERGÊNCIA ATIVADA", msg_esd)
                await ws.send_text(json.dumps({
                    "type": "esd", "status": "triggered", "message": msg_esd
                }))

            elif cmd == "esd_reset":
                msg_reset = plant.reset_esd()
                db.record_event("info", "ESD_RESET", "ESD resetado pelo operador", msg_reset)
                await ws.send_text(json.dumps({
                    "type": "esd", "status": "reset", "message": msg_reset
                }))

            elif cmd == "ping":
                await ws.send_text(json.dumps({"type": "pong", "ts": time.time()}))

        except json.JSONDecodeError:
            await ws.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
        except Exception as e:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))

    # ── REST API ──────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def serve_frontend():
        """Serve the SCADA frontend."""
        if os.path.exists(FRONTEND_PATH):
            with open(FRONTEND_PATH, "r", encoding="utf-8") as f:
                html = f.read()
            # Patch the HTML to connect to the real backend WebSocket
            html = html.replace(
                "// WEBSOCKET_ENDPOINT",
                f"const WS_URL = 'ws://localhost:{PORT}/ws';"
            )
            return HTMLResponse(html)
        return HTMLResponse("<h1>AquaH2 SCADA</h1><p>Frontend HTML not found. "
                            f"Expected: {FRONTEND_PATH}</p>")

    @app.get("/api/v1/state")
    async def get_state():
        return JSONResponse(plant.to_dict())

    @app.get("/api/v1/alarms")
    async def get_alarms():
        return JSONResponse({
            "active": ai.get_alarm_list(),
            "history": ai.get_alarm_history(50)
        })

    @app.get("/api/v1/events")
    async def get_events(hours: float = 24.0, limit: int = 100):
        return JSONResponse(db.get_events(limit=limit, hours=hours))

    @app.get("/api/v1/history/{tag}")
    async def get_history(tag: str, hours: float = 24.0, max_points: int = 500):
        data = db.get_history(tag, hours, max_points)
        return JSONResponse({"tag": tag, "hours": hours, "points": data})

    @app.get("/api/v1/history")
    async def get_multi_history(hours: float = 24.0):
        tags = ["stack_a_temp", "stack_b_temp", "stack_a_h2", "stack_b_h2",
                "solar_mw", "wind_mw", "bess_soc", "swro_salinity", "nh3_rate"]
        data = db.get_multi_history(tags, hours)
        return JSONResponse(data)

    @app.post("/api/v1/setpoint")
    async def set_setpoint(body: Dict[str, Any]):
        tag = body.get("tag")
        val = body.get("value")
        if not tag or val is None:
            raise HTTPException(400, "tag and value required")
        old = plant.get_setpoints().get(tag, 0)
        ok = plant.apply_setpoint(tag, float(val))
        if ok:
            db.record_setpoint(tag, old, float(val), "api")
        return JSONResponse({"ok": ok, "tag": tag, "value": val})

    @app.post("/api/v1/toggle")
    async def set_toggle(body: Dict[str, Any]):
        key = body.get("key")
        val = body.get("value")
        if key is None or val is None:
            raise HTTPException(400, "key and value required")
        ok = plant.apply_toggle(key, bool(val))
        return JSONResponse({"ok": ok, "key": key, "value": val})

    @app.post("/api/v1/chat")
    async def post_chat(body: Dict[str, Any]):
        message = body.get("message", "")
        if not message:
            raise HTTPException(400, "message required")
        response = await ai.chat(message)
        return JSONResponse({"response": response, "ts": time.time()})

    @app.post("/api/v1/alarms/ack")
    async def ack_alarm(body: Dict[str, Any]):
        code = body.get("code", "")
        operator = body.get("operator", "operator")
        ok = ai.acknowledge_alarm(code, operator)
        return JSONResponse({"ok": ok, "code": code})

    @app.post("/api/v1/esd")
    async def trigger_esd():
        msg = plant.trigger_esd()
        db.record_event("trip", "ESD", "PARADA DE EMERGÊNCIA", msg)
        return JSONResponse({"status": "triggered", "message": msg})

    @app.post("/api/v1/esd/reset")
    async def reset_esd_endpoint():
        msg = plant.reset_esd()
        db.record_event("info", "ESD_RESET", "ESD reset", msg)
        return JSONResponse({"status": "reset", "message": msg})

    @app.get("/api/v1/ai/status")
    async def get_ai_status():
        return JSONResponse(ai.get_status())

    @app.get("/api/v1/network")
    async def get_network():
        return JSONResponse(plant.get_network_status())

    @app.get("/api/v1/db/stats")
    async def get_db_stats():
        return JSONResponse(db.get_stats())

    # ── Run ───────────────────────────────────────────────────────────

    def run():
        uvicorn.run(app, host=HOST, port=PORT, log_level="info")


# ══════════════════════════════════════════════════════════════════════
# STDLIB FALLBACK (no FastAPI)
# ══════════════════════════════════════════════════════════════════════

else:
    import asyncio
    import websockets

    WS_CLIENTS: Set = set()

    async def sensor_task():
        while True:
            state = plant.tick()
            data = plant.to_dict()
            db.record_sensors(data)
            ai.ingest(plant.state)
            msg = json.dumps({"type": "state", "data": data})
            for ws in list(WS_CLIENTS):
                try:
                    await ws.send(msg)
                except Exception:
                    WS_CLIENTS.discard(ws)
            await asyncio.sleep(SIM_TICK_INTERVAL_S)

    async def ai_task():
        async def on_decision(d):
            msg = json.dumps({"type": "ai_decision", "data": d.to_dict()})
            for ws in list(WS_CLIENTS):
                try:
                    await ws.send(msg)
                except Exception:
                    WS_CLIENTS.discard(ws)
        while True:
            decisions = ai.analyze_and_decide()
            for d in decisions:
                if d.action_type in ("setpoint", "toggle"):
                    if d.action_type == "setpoint":
                        plant.apply_setpoint(d.target, d.value)
                    else:
                        plant.apply_toggle(d.target, d.value)
                ai.decision_history.append(d)
                await on_decision(d)
            await asyncio.sleep(AI_DECISION_INTERVAL_S)

    async def ws_handler(websocket, path):
        WS_CLIENTS.add(websocket)
        await websocket.send(json.dumps({"type": "state", "data": plant.to_dict()}))
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                    cmd = msg.get("cmd", "")
                    payload = msg.get("data", {})
                    if cmd == "setpoint":
                        plant.apply_setpoint(payload["tag"], float(payload["value"]))
                        await websocket.send(json.dumps({"type": "ack", "ok": True}))
                    elif cmd == "toggle":
                        plant.apply_toggle(payload["key"], bool(payload["value"]))
                        await websocket.send(json.dumps({"type": "ack", "ok": True}))
                    elif cmd == "chat":
                        resp = await ai.chat(payload.get("message", ""))
                        await websocket.send(json.dumps({
                            "type": "chat_response", "message": resp, "ts": time.time()}))
                    elif cmd == "esd":
                        msg_esd = plant.trigger_esd()
                        await websocket.send(json.dumps({"type": "esd", "message": msg_esd}))
                    elif cmd == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                except Exception as e:
                    await websocket.send(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
        finally:
            WS_CLIENTS.discard(websocket)

    async def main_async():
        print(f"\n{'='*60}")
        print(f"  AquaH2 AI-SCADA (stdlib fallback — no FastAPI)")
        print(f"  WebSocket: ws://localhost:{PORT}/ws")
        print(f"  Note: Install fastapi uvicorn for full REST API + frontend serving")
        print(f"{'='*60}\n")
        async with websockets.serve(ws_handler, HOST, PORT):
            await asyncio.gather(sensor_task(), ai_task())

    def run():
        asyncio.run(main_async())


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Backend mode: {'FastAPI + Uvicorn' if USE_FASTAPI else 'stdlib WebSockets'}")
    run()
