"""
AquaH2 AI-SCADA — WebSocket Client Injector
Patches the standalone HTML to connect to the real Python backend.

Usage:
    python patch_frontend.py
    
This reads aquah2_platform.html and produces aquah2_connected.html
which talks to the backend via WebSocket.

Kraefegg M.O. · Developer: Railson
"""

import os
import re

FRONTEND_IN  = os.path.join(os.path.dirname(__file__), "..", "aquah2_platform.html")
FRONTEND_OUT = os.path.join(os.path.dirname(__file__), "..", "aquah2_connected.html")

WS_CLIENT_JS = r"""
/* ═══════════════════════════════════════════════════════════════════
   AquaH2 REAL BACKEND WebSocket CLIENT
   Replaces simulated data with live data from Python server
   ══════════════════════════════════════════════════════════════════ */
(function() {
  var WS_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'ws://' + window.location.hostname + ':8765/ws'
    : 'ws://' + window.location.host + '/ws';

  var ws = null;
  var reconnectDelay = 2000;
  var connected = false;

  function connect() {
    try {
      ws = new WebSocket(WS_URL);
    } catch(e) {
      console.warn('[WS] Cannot connect:', e);
      scheduleReconnect();
      return;
    }

    ws.onopen = function() {
      connected = true;
      reconnectDelay = 2000;
      console.log('[WS] Connected to AquaH2 backend:', WS_URL);
      showConnectionBanner(true);
    };

    ws.onclose = function() {
      connected = false;
      console.warn('[WS] Disconnected. Reconnecting in', reconnectDelay, 'ms...');
      showConnectionBanner(false);
      scheduleReconnect();
    };

    ws.onerror = function(e) {
      console.error('[WS] Error:', e);
    };

    ws.onmessage = function(ev) {
      try {
        var msg = JSON.parse(ev.data);
        handleMessage(msg);
      } catch(e) {
        console.error('[WS] Parse error:', e);
      }
    };
  }

  function scheduleReconnect() {
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
  }

  /* ── Message dispatcher ──────────────────────────────── */
  function handleMessage(msg) {
    if (msg.type === 'state') {
      applyState(msg.data);
    } else if (msg.type === 'ai_decision') {
      appendAIDecision(msg.data);
    } else if (msg.type === 'alarms') {
      applyAlarms(msg.data);
    } else if (msg.type === 'chat_response') {
      deliverChatResponse(msg.message);
    } else if (msg.type === 'esd') {
      alert('ESD: ' + msg.message);
    } else if (msg.type === 'error') {
      console.error('[Backend Error]', msg.message);
    }
  }

  /* ── Apply full plant state to UI ────────────────────── */
  function applyState(d) {
    var sa = d.stack_a || {}, sb = d.stack_b || {};
    var en = d.energy || {}, bs = d.bess || {};
    var sw = d.swro || {}, h2 = d.h2_storage || {}, nh = d.nh3 || {};

    // Header
    var h2Total = (sa.h2_production || 0) + (sb.h2_production || 0);
    set('h-h2',    (h2Total * 0.0898 / 1000 * 3600 / 1000).toFixed(1) + ' kg/h');
    set('h-pwr',   fmt(en.total_mw, 1) + ' MW');
    set('h-eff',   fmt(sa.efficiency_lhv, 1) + '%');
    set('h-water', fmt(sw.product_flow, 2) + ' m³/min');
    set('h-bess',  Math.round(bs.soc || 0) + '%');
    set('h-nh3',   fmt(nh.tank_level_pct, 0) + '%');

    // KPIs
    set('kpi-h2',    fmt(h2Total * 0.0898 / 1000 * 3600 / 1000, 1) + ' <span style="font-size:13px;color:var(--txt2)">kg/h</span>');
    set('kpi-pwr',   fmt(en.total_mw, 1) + ' <span style="font-size:13px;color:var(--txt2)">MW</span>');
    set('kpi-water', fmt((sw.product_flow || 0) * 1440, 0) + ' <span style="font-size:13px;color:var(--txt2)">m³/dia</span>');
    set('kpi-nh3',   fmt((nh.production_kgh || 0) * 24 / 1000, 2) + ' <span style="font-size:13px;color:var(--txt2)">t</span>');

    // Overview sensors
    set('ov-ta', fmt(sa.temp_cell, 1) + ' °C', 'sval ' + (sa.temp_cell > 78 ? 'warn' : 'ok'));
    set('ov-tb', fmt(sb.temp_cell, 1) + ' °C', 'sval ' + (sb.temp_cell > 78 ? 'warn' : 'ok'));
    set('ov-press', fmt(sa.pressure_h2, 1) + ' bar');
    set('ov-swro-press', fmt(sw.feed_pressure, 1) + ' bar');

    // Rings
    updateRing('ring-eff', sa.efficiency_lhv / 100, sa.efficiency_lhv < 68 ? 'var(--amber)' : 'var(--teal)');
    setEl('ring-eff-val', fmt(sa.efficiency_lhv, 1));
    updateRing('ring-bess', bs.soc / 100, '#10B981');
    setEl('ring-bess-val', Math.round(bs.soc));

    // Electrolyzer tables
    setSensor('elec-a-temp',  fmt(sa.temp_cell, 1) + ' °C', sa.temp_cell > 78 ? 'sval warn' : 'sval ok');
    setSensor('elec-a-press', fmt(sa.pressure_h2, 1) + ' bar', sa.pressure_h2 > 33 ? 'sval warn' : 'sval');
    setSensor('elec-a-curr',  Math.round(sa.current_dc || 0) + ' A', 'sval');
    setSensor('elec-a-flow',  fmt(sa.water_flow_actual, 1) + ' L/min', 'sval');
    setSensor('elec-a-h2',    Math.round(sa.h2_production || 0) + ' Nm³/h', 'sval ok');
    setSensor('elec-b-temp',  fmt(sb.temp_cell, 1) + ' °C', sb.temp_cell > 78 ? 'sval warn' : 'sval ok');
    setSensor('elec-b-press', fmt(sb.pressure_h2, 1) + ' bar', sb.pressure_h2 > 34 ? 'sval warn' : 'sval');
    setSensor('elec-b-curr',  Math.round(sb.current_dc || 0) + ' A', 'sval');
    setSensor('elec-b-flow',  fmt(sb.water_flow_actual, 1) + ' L/min', 'sval');
    setSensor('elec-b-h2',    Math.round(sb.h2_production || 0) + ' Nm³/h', 'sval ok');

    // Energy
    set('en-solar', fmt(en.solar_mw, 1) + ' <span style="font-size:13px;color:var(--txt2)">MW</span>');
    set('en-wind',  fmt(en.wind_mw, 1) + ' <span style="font-size:13px;color:var(--txt2)">MW</span>');
    set('en-bess',  Math.round(bs.soc) + ' <span style="font-size:13px;color:var(--txt2)">%</span>');
    set('en-irr',   Math.round(en.irradiance || 0) + ' W/m²');
    set('en-wspd',  fmt(en.wind_speed, 1) + ' m/s');
    set('en-bess-soc', Math.round(bs.soc) + '%');
    set('bess-kwh', fmt((bs.soc || 0) * 0.20, 1) + ' MWh');

    // SWRO
    set('swro-feed-press', fmt(sw.feed_pressure, 1) + ' bar');
    set('swro-temp', fmt(sw.water_temp, 1) + ' °C');

    // PFD
    set('pfd-ta', fmt(sa.temp_cell,1)+'°C · '+fmt(sa.pressure_h2,1)+' bar');
    set('pfd-tb', fmt(sb.temp_cell,1)+'°C · '+fmt(sb.pressure_h2,1)+' bar');
    set('pfd-ha', Math.round(sa.h2_production||0)+' Nm³/h H₂');
    set('pfd-hb', Math.round(sb.h2_production||0)+' Nm³/h H₂');
    set('pfd-h2total', Math.round(h2Total)+' Nm³/h');
    set('pfd-solar', fmt(en.solar_mw,1)+' MW');
    set('pfd-wind',  fmt(en.wind_mw,1)+' MW');
    set('pfd-total-pwr', fmt(en.total_mw,1)+' MW total');
    set('pfd-bess', Math.round(bs.soc)+'% SoC');
    set('pfd-h2tank', fmt(h2.tank_level_pct,0)+'% · '+fmt(h2.tank_mass_t,1)+'t');
    set('pfd-nh3rate', fmt(nh.production_kgh,0)+' kg/h');

    // Log
    addLog('[DATA] A:'+fmt(sa.temp_cell,1)+'°C/'+fmt(sa.pressure_h2,1)+'bar/'+Math.round(sa.h2_production)+'Nm³h  B:'+fmt(sb.temp_cell,1)+'°C/'+fmt(sb.pressure_h2,1)+'bar  E:'+fmt(en.total_mw,1)+'MW  BESS:'+Math.round(bs.soc)+'%');
  }

  function applyAlarms(alarms) {
    var badge = document.getElementById('nav-alarm-badge');
    var hdrBtn = document.getElementById('alarm-btn');
    var hdrCount = document.getElementById('alarm-count');
    var active = alarms.filter(function(a){ return !a.acknowledged; });
    if (badge) badge.textContent = active.length;
    if (hdrCount) hdrCount.textContent = active.length + ' Alarme' + (active.length !== 1 ? 's' : '');
    if (hdrBtn) {
      if (active.length > 0) {
        hdrBtn.className = 'hdr-alarm-btn';
      } else {
        hdrBtn.className = 'hdr-alarm-btn clear';
      }
    }
  }

  function appendAIDecision(d) {
    addLog('[AI] ' + d.reason.substring(0, 100) + ' (conf:' + d.confidence + ')');
  }

  /* ── Chat integration ────────────────────────────────── */
  var _chatResolve = null;
  window._ws_sendChat = function(message) {
    return new Promise(function(resolve) {
      _chatResolve = resolve;
      sendCmd('chat', { message: message });
    });
  };

  function deliverChatResponse(text) {
    if (_chatResolve) {
      _chatResolve(text);
      _chatResolve = null;
    }
  }

  /* ── Command senders ─────────────────────────────────── */
  function sendCmd(cmd, data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ cmd: cmd, data: data }));
    } else {
      console.warn('[WS] Not connected, queuing command:', cmd);
    }
  }

  /* ── Expose to global scope ──────────────────────────── */
  window._ws = {
    sendSetpoint: function(tag, value) { sendCmd('setpoint', {tag: tag, value: value}); },
    sendToggle:   function(key, value) { sendCmd('toggle',   {key: key, value: value}); },
    sendESD:      function()           { sendCmd('esd',      {}); },
    resetESD:     function()           { sendCmd('esd_reset',{}); },
    ackAlarm:     function(code, op)   { sendCmd('ack_alarm',{code: code, operator: op}); },
    isConnected:  function()           { return connected; },
  };

  /* ── Helpers ─────────────────────────────────────────── */
  function fmt(v, d) {
    if (v === undefined || v === null) return '--';
    return parseFloat(v).toFixed(d);
  }
  function set(id, html, cls) {
    var el = document.getElementById(id); if (!el) return;
    if (cls !== undefined) el.className = cls;
    el.innerHTML = html;
  }
  function setEl(id, text) {
    var el = document.getElementById(id); if (el) el.textContent = text;
  }
  function setSensor(id, html, cls) {
    var el = document.getElementById(id); if (!el) return;
    el.className = cls || 'sval'; el.innerHTML = html;
  }
  function updateRing(id, pct, color) {
    var el = document.getElementById(id); if (!el) return;
    var offset = 201 - (201 * Math.max(0, Math.min(1, pct)));
    el.setAttribute('stroke-dashoffset', offset.toFixed(1));
    if (color) el.setAttribute('stroke', color);
  }
  function addLog(text) {
    var area = document.getElementById('sys-log'); if (!area) return;
    var d = document.createElement('div');
    d.textContent = '[' + new Date().toTimeString().slice(0,8) + '] ' + text;
    d.style.color = text.includes('[AI]') ? '#8B5CF6' : text.includes('[WARN]') ? '#F59E0B' : 'var(--txt2)';
    area.appendChild(d);
    if (area.children.length > 120) area.removeChild(area.firstChild);
    area.scrollTop = area.scrollHeight;
  }
  function showConnectionBanner(ok) {
    var el = document.getElementById('hdr-status');
    if (el) el.textContent = ok
      ? 'Conectado ao backend Python · Dados reais'
      : 'Reconectando ao backend...';
    var dot = document.getElementById('hdr-dot');
    if (dot) dot.className = 'hdr-dot' + (ok ? '' : ' warn');
  }

  /* ── Override sendChat to use WebSocket ──────────────── */
  document.addEventListener('DOMContentLoaded', function() {
    var origSendChat = window.sendChat;
    window.sendChat = function() {
      var inp = document.getElementById('chat-inp');
      var v = inp ? inp.value.trim() : '';
      if (!v) return;
      if (typeof addMsg === 'function') addMsg(v, true);
      inp.value = '';
      var think = document.createElement('div');
      think.className = 'chat-thinking';
      think.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div>';
      var area = document.getElementById('chat-area');
      if (area) { area.appendChild(think); area.scrollTop = 99999; }
      if (window._ws_sendChat) {
        window._ws_sendChat(v).then(function(resp) {
          if (think.parentNode) think.remove();
          if (typeof addMsg === 'function') addMsg(resp, false);
        });
      } else {
        if (think.parentNode) think.remove();
        if (origSendChat) origSendChat();
      }
    };
  });

  /* ── Connect on load ─────────────────────────────────── */
  connect();
  console.log('[AquaH2] WebSocket client initialized. URL:', WS_URL);
})();
"""


def patch(html_in: str) -> str:
    """Inject WebSocket client before </body>."""
    inject = f"\n<script>\n{WS_CLIENT_JS}\n</script>\n</body>"
    return html_in.replace("</body>", inject, 1)


if __name__ == "__main__":
    if not os.path.exists(FRONTEND_IN):
        print(f"ERROR: Frontend not found at {FRONTEND_IN}")
        print("Run from the project root or adjust paths.")
        exit(1)
    with open(FRONTEND_IN, "r", encoding="utf-8") as f:
        html = f.read()
    patched = patch(html)
    with open(FRONTEND_OUT, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"Patched frontend written to: {FRONTEND_OUT}")
    print(f"Open in browser AFTER starting main.py")
