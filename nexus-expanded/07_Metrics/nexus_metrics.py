"""
NEXUS v4.0 - Metrics & Events
Exports operational telemetry to Prometheus and fires webhook notifications.

Prometheus metrics exposed at :9090/metrics (default):
  nexus_solver_latency_ms       — spigot_torch solve time
  nexus_loop_latency_ms         — total control loop time
  nexus_fan_setpoint{zone}      — current fan setpoint per zone
  nexus_prediction{zone}        — solver prediction per zone (normalized)
  nexus_input{slot, source}     — input vector values per slot
  nexus_actuation_total         — total actuation count
  nexus_error_total             — total error count
  nexus_trial_days_remaining    — trial license days remaining

Webhook events fired on:
  - Solver prediction above configurable threshold
  - Actuation failure
  - Input source going stale
  - Trial license expiration warning
"""

import time
import json
import logging
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Prometheus metrics (pure Python, no library required)
# ─────────────────────────────────────────────────────────

class MetricsRegistry:
    """
    Lightweight Prometheus-compatible metrics registry.
    No external dependencies — generates /metrics text format directly.
    """

    def __init__(self):
        self._gauges = {}
        self._counters = {}
        self._histograms = {}
        self._lock = threading.Lock()

    def set_gauge(self, name: str, value: float, labels: dict = None):
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = {
                "name": name, "value": value,
                "labels": labels or {}, "ts": time.time()
            }

    def inc_counter(self, name: str, amount: float = 1.0, labels: dict = None):
        key = self._key(name, labels)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = {"name": name, "value": 0.0,
                                       "labels": labels or {}}
            self._counters[key]["value"] += amount

    def observe_histogram(self, name: str, value: float, labels: dict = None):
        """Simple summary-style histogram (p50, p95, p99)."""
        key = self._key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = {
                    "name": name, "labels": labels or {},
                    "samples": [], "count": 0, "sum": 0.0
                }
            h = self._histograms[key]
            h["samples"].append(value)
            if len(h["samples"]) > 1000:
                h["samples"] = h["samples"][-1000:]
            h["count"] += 1
            h["sum"] += value

    def _key(self, name: str, labels: Optional[dict]) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _label_str(self, labels: dict) -> str:
        if not labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"

    def _percentile(self, samples: list, pct: float) -> float:
        if not samples:
            return 0.0
        sorted_s = sorted(samples)
        idx = int(len(sorted_s) * pct / 100)
        return sorted_s[min(idx, len(sorted_s) - 1)]

    def render(self) -> str:
        """Generate Prometheus text format output."""
        lines = []
        with self._lock:
            for key, g in self._gauges.items():
                lines.append(f"# HELP {g['name']} NEXUS operational metric")
                lines.append(f"# TYPE {g['name']} gauge")
                lines.append(
                    f"{g['name']}{self._label_str(g['labels'])} {g['value']:.6f}")

            for key, c in self._counters.items():
                lines.append(f"# HELP {c['name']} NEXUS counter")
                lines.append(f"# TYPE {c['name']} counter")
                lines.append(
                    f"{c['name']}{self._label_str(c['labels'])}_total {c['value']:.0f}")

            for key, h in self._histograms.items():
                lines.append(f"# HELP {h['name']} NEXUS latency histogram")
                lines.append(f"# TYPE {h['name']} summary")
                label_str = self._label_str(h["labels"])
                for q, pct in [(0.5, 50), (0.95, 95), (0.99, 99)]:
                    val = self._percentile(h["samples"], pct)
                    q_labels = dict(h["labels"])
                    q_labels["quantile"] = str(q)
                    lines.append(
                        f"{h['name']}{self._label_str(q_labels)} {val:.6f}")
                lines.append(f"{h['name']}_sum{label_str} {h['sum']:.6f}")
                lines.append(f"{h['name']}_count{label_str} {h['count']}")

        return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────
# Metrics HTTP server
# ─────────────────────────────────────────────────────────

class MetricsHTTPHandler(BaseHTTPRequestHandler):
    registry = None

    def do_GET(self):
        if self.path == "/metrics":
            content = self.registry.render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs


class NexusMetricsExporter:
    """
    Exposes NEXUS metrics on a Prometheus-compatible HTTP endpoint.
    Scrape from Prometheus, Grafana Agent, or any OpenMetrics-compatible tool.
    Default: http://0.0.0.0:9090/metrics
    """

    def __init__(self, config: dict):
        self.port = config.get("metrics_port", 9090)
        self.registry = MetricsRegistry()
        self._server = None
        self._thread = None
        self._start_time = time.time()

        MetricsHTTPHandler.registry = self.registry

    def start(self):
        self._server = HTTPServer(("0.0.0.0", self.port), MetricsHTTPHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Metrics exporter: http://0.0.0.0:{self.port}/metrics")

    def stop(self):
        if self._server:
            self._server.shutdown()

    def update_from_loop(self, input_vector: list, predictions: list,
                         solver_ms: float, loop_ms: float,
                         actuation_result: dict, zone_setpoints: dict):
        """Called after each control loop to update all metrics."""
        r = self.registry

        # Latency
        r.observe_histogram("nexus_solver_latency_ms", solver_ms)
        r.observe_histogram("nexus_loop_latency_ms", loop_ms)
        r.set_gauge("nexus_solver_latency_ms_last", solver_ms)
        r.set_gauge("nexus_loop_latency_ms_last", loop_ms)

        # Predictions per zone
        for i, p in enumerate(predictions[:12]):
            r.set_gauge("nexus_prediction", p, {"zone": str(i)})

        # Fan setpoints
        for zone_id, setpoint in zone_setpoints.items():
            r.set_gauge("nexus_fan_setpoint_pct", setpoint,
                        {"zone": str(zone_id)})

        # Input vector (sampled slots of interest)
        slot_names = {
            0: "cpu0_power", 1: "cpu1_power", 4: "gpu0_power", 5: "gpu1_power",
            8: "mem_power", 12: "cpu0_temp", 16: "gpu0_temp",
            20: "ambient_inlet", 21: "ambient_outlet",
            22: "coolant_inlet", 23: "coolant_outlet"
        }
        for slot, name in slot_names.items():
            if slot < len(input_vector):
                r.set_gauge("nexus_input_normalized", input_vector[slot],
                            {"slot": str(slot), "signal": name})

        # Actuation counters
        r.inc_counter("nexus_actuation", actuation_result.get("actuations", 0))
        r.inc_counter("nexus_actuation_errors", actuation_result.get("errors", 0))

        # Uptime
        r.set_gauge("nexus_uptime_seconds", time.time() - self._start_time)

    def update_trial_status(self, days_remaining: float):
        self.registry.set_gauge("nexus_trial_days_remaining", days_remaining)


# ─────────────────────────────────────────────────────────
# Webhook event bus
# ─────────────────────────────────────────────────────────

class NexusEventBus:
    """
    Fires webhook notifications on thermal events.
    Supports multiple endpoints (Slack, PagerDuty, generic HTTP).
    Non-blocking — events dispatched in background threads.
    """

    EVENT_TYPES = {
        "THERMAL_WARNING":   {"severity": "warning",  "color": "#FFA500"},
        "THERMAL_CRITICAL":  {"severity": "critical", "color": "#FF0000"},
        "THERMAL_NORMAL":    {"severity": "info",     "color": "#00FF00"},
        "ACTUATION_FAILURE": {"severity": "error",    "color": "#FF4444"},
        "SOLVER_TIMEOUT":    {"severity": "error",    "color": "#FF4444"},
        "INPUT_STALE":       {"severity": "warning",  "color": "#FFA500"},
        "TRIAL_EXPIRING":    {"severity": "warning",  "color": "#FFA500"},
        "TRIAL_EXPIRED":     {"severity": "critical", "color": "#FF0000"},
    }

    def __init__(self, config: dict):
        self.endpoints = config.get("webhook_endpoints", [])
        self.hostname = config.get("hostname", os.uname().nodename
                                   if hasattr(os, "uname") else "unknown")
        self._cooldown = {}  # event_type -> last_fired_ts
        self.cooldown_s = config.get("event_cooldown_s", 60)

    def fire(self, event_type: str, detail: str = "", data: dict = None):
        """Fire event to all configured webhook endpoints."""
        if not self.endpoints:
            return

        # Cooldown — don't spam the same event type
        now = time.time()
        last = self._cooldown.get(event_type, 0)
        if (now - last) < self.cooldown_s:
            return
        self._cooldown[event_type] = now

        meta = self.EVENT_TYPES.get(event_type, {"severity": "info", "color": "#888"})
        event = {
            "event_type": event_type,
            "severity": meta["severity"],
            "hostname": self.hostname,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "detail": detail,
            "data": data or {},
        }

        for endpoint in self.endpoints:
            threading.Thread(
                target=self._send,
                args=(endpoint, event, meta["color"]),
                daemon=True
            ).start()

    def _send(self, endpoint: dict, event: dict, color: str):
        url = endpoint.get("url", "")
        if not url:
            return
        endpoint_type = endpoint.get("type", "generic").lower()

        try:
            if endpoint_type == "slack":
                payload = self._format_slack(event, color)
            elif endpoint_type == "pagerduty":
                payload = self._format_pagerduty(event)
            else:
                payload = event  # Raw JSON for generic endpoints

            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                logger.debug(f"Event {event['event_type']} → {url}: {resp.status}")
        except Exception as e:
            logger.warning(f"Webhook delivery failed to {url}: {e}")

    def _format_slack(self, event: dict, color: str) -> dict:
        return {
            "attachments": [{
                "color": color,
                "title": f"NEXUS: {event['event_type']}",
                "text": event["detail"],
                "fields": [
                    {"title": "Host", "value": event["hostname"], "short": True},
                    {"title": "Severity", "value": event["severity"], "short": True},
                    {"title": "Time", "value": event["timestamp"], "short": False},
                ],
                "footer": "NEXUS Thermal Engine · LFM"
            }]
        }

    def _format_pagerduty(self, event: dict) -> dict:
        severity_map = {
            "critical": "critical", "error": "error",
            "warning": "warning", "info": "info"
        }
        return {
            "routing_key": "",  # Set in endpoint config
            "event_action": "trigger",
            "payload": {
                "summary": f"NEXUS {event['event_type']} on {event['hostname']}",
                "severity": severity_map.get(event["severity"], "info"),
                "source": event["hostname"],
                "custom_details": event["data"],
                "timestamp": event["timestamp"],
            }
        }


# ─────────────────────────────────────────────────────────
# SNMP trap sender (legacy PDU / network gear)
# ─────────────────────────────────────────────────────────

class SNMPTrapSender:
    """
    Send SNMP v2c traps for thermal events.
    For integrating with legacy DCIM systems that use SNMP.
    Requires: snmptrap (net-snmp) installed.
    """

    def __init__(self, config: dict):
        self.manager_host = config.get("snmp_manager_host", "")
        self.community = config.get("snmp_community", "public")
        self.oid_prefix = config.get("snmp_oid_prefix", "1.3.6.1.4.1.99999")
        self._available = bool(self.manager_host) and self._check_snmptrap()

    def _check_snmptrap(self) -> bool:
        try:
            import subprocess
            result = subprocess.run(["snmptrap", "--version"],
                                    capture_output=True, timeout=3)
            return True
        except FileNotFoundError:
            logger.info("snmptrap not found — SNMP trap output disabled")
            return False

    def send_thermal_trap(self, zone_id: int, prediction: float,
                           event_type: str = "thermalWarning"):
        if not self._available:
            return
        import subprocess
        trap_oid = f"{self.oid_prefix}.1.{zone_id}"
        value_oid = f"{self.oid_prefix}.2.{zone_id}"
        cmd = [
            "snmptrap", "-v", "2c", "-c", self.community,
            self.manager_host, "", trap_oid,
            value_oid, "i", str(int(prediction * 100))
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
        except Exception as e:
            logger.debug(f"SNMP trap error: {e}")
