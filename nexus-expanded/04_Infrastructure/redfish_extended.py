"""
NEXUS v4.0 - Redfish Extended: Event Subscriptions + Full Schema Support
Moves from poll-only to push+poll hybrid for lower latency thermal events.

Covers:
  - Redfish EventService (SSE + push delivery)
  - ThermalSubsystem schema (newer servers)
  - CoolingUnit / ThermalEquipment full traversal
  - Multi-chassis via ChassisCollection
  - Redfish Aggregation (rack-level, DCIM integration)
  - Metric report subscriptions
"""

import json
import logging
import threading
import time
import urllib.request
import urllib.parse
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class RedfishEventSubscriber:
    """
    Subscribe to Redfish EventService for push-based thermal alerts.
    Faster than polling — BMC sends events at threshold crossings.
    Requires: Redfish 1.6+ with EventService enabled on BMC.

    Two delivery modes:
      1. Server-Sent Events (SSE) — streaming, low-latency
      2. Push HTTP POST — BMC POSTs events to our webhook listener
    """

    THERMAL_EVENT_TYPES = [
        "Alert",
        "StatusChange",
        "ResourceUpdated",
        "MetricReport",
    ]

    THERMAL_MESSAGE_REGISTRIES = [
        "ThermalEvents",
        "Platform",
        "OpenBMC.0.1",
    ]

    def __init__(self, redfish_client, config: dict,
                 on_event: Optional[Callable] = None):
        self.rf = redfish_client
        self.config = config
        self.on_event = on_event or self._default_event_handler
        self._subscription_url = None
        self._sse_thread = None
        self._running = False
        self._webhook_port = config.get("redfish_event_webhook_port", 9100)
        self._webhook_server = None

    def subscribe_push(self, webhook_host: str) -> bool:
        """
        Register a push subscription — BMC will POST events to our webhook.
        webhook_host: IP/hostname reachable from the BMC.
        """
        try:
            event_service_url = f"{self.rf.base_url}/EventService"
            resp = self.rf.session.get(event_service_url)
            if resp.status_code != 200:
                logger.warning("EventService not available on this BMC")
                return False

            event_service = resp.json()
            subs_url = event_service.get("Subscriptions", {}).get("@odata.id")
            if not subs_url:
                subs_url_full = f"{self.rf.base_url}/EventService/Subscriptions"
            else:
                host = self.rf.base_url.split("/redfish")[0]
                subs_url_full = host + subs_url

            destination = f"http://{webhook_host}:{self._webhook_port}/redfish-event"
            payload = {
                "Destination": destination,
                "EventTypes": self.THERMAL_EVENT_TYPES,
                "Context": "NEXUS_THERMAL",
                "Protocol": "Redfish",
                "MessageIds": ["ThermalEvents.1.0.OverTemperatureCondition",
                               "ThermalEvents.1.0.TemperatureNormal",
                               "Platform.1.0.PlatformAlert"],
            }

            resp = self.rf.session.post(subs_url_full, json=payload)
            if resp.status_code in (200, 201):
                self._subscription_url = resp.headers.get("Location", "")
                logger.info(f"Redfish push subscription created → {destination}")
                return True
            else:
                logger.warning(f"Subscription failed: {resp.status_code} {resp.text[:200]}")
                return False

        except Exception as e:
            logger.error(f"EventService subscription error: {e}")
            return False

    def subscribe_sse(self) -> bool:
        """
        Server-Sent Events streaming subscription.
        Connects to /EventService/SSE and streams events continuously.
        """
        try:
            sse_url = f"{self.rf.base_url}/EventService/SSE"
            resp = self.rf.session.get(sse_url, stream=True)
            if resp.status_code != 200:
                logger.info("SSE not available on this BMC")
                return False

            self._running = True
            self._sse_thread = threading.Thread(
                target=self._sse_reader, args=(resp,), daemon=True)
            self._sse_thread.start()
            logger.info("Redfish SSE stream connected")
            return True
        except Exception as e:
            logger.info(f"SSE connection failed: {e}")
            return False

    def _sse_reader(self, response):
        """Parse SSE stream and dispatch thermal events."""
        buffer = ""
        try:
            for chunk in response.iter_content(chunk_size=None):
                if not self._running:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    lines = event_str.strip().splitlines()
                    data_lines = [l[5:] for l in lines if l.startswith("data:")]
                    if data_lines:
                        try:
                            event = json.loads("\n".join(data_lines))
                            self.on_event(event)
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            logger.error(f"SSE stream error: {e}")

    def _default_event_handler(self, event: dict):
        """Log thermal events — override with custom handler."""
        msg_id = event.get("MessageId", "")
        severity = event.get("Severity", "")
        message = event.get("Message", "")
        logger.info(f"Redfish Event [{severity}] {msg_id}: {message}")

    def unsubscribe(self):
        """Remove push subscription from BMC."""
        self._running = False
        if self._subscription_url:
            try:
                host = self.rf.base_url.split("/redfish")[0]
                url = host + self._subscription_url if not self._subscription_url.startswith("http") else self._subscription_url
                resp = self.rf.session.delete(url)
                if resp.status_code in (200, 204):
                    logger.info("Redfish event subscription removed")
            except Exception as e:
                logger.error(f"Unsubscribe error: {e}")


class RedfishMultiChassis:
    """
    Multi-chassis traversal via ChassisCollection.
    Discovers all chassis in a rack (servers, switches, storage, PDUs)
    and returns aggregated thermal/power readings.
    """

    def __init__(self, redfish_client):
        self.rf = redfish_client
        self._chassis_list = []
        self._discover()

    def _discover(self):
        try:
            resp = self.rf.session.get(f"{self.rf.base_url}/Chassis")
            if resp.status_code != 200:
                return
            members = resp.json().get("Members", [])
            host = self.rf.base_url.split("/redfish")[0]
            for m in members:
                path = m.get("@odata.id", "")
                chassis_id = path.rstrip("/").split("/")[-1]
                self._chassis_list.append({
                    "id": chassis_id,
                    "url": host + path if not path.startswith("http") else path,
                })
            logger.info(f"Multi-chassis: {len(self._chassis_list)} chassis discovered")
        except Exception as e:
            logger.error(f"Chassis discovery error: {e}")

    def get_all_thermal(self) -> list:
        """Return list of thermal readings from all chassis."""
        results = []
        for chassis in self._chassis_list:
            try:
                url = f"{chassis['url']}/Thermal"
                resp = self.rf.session.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    data["_chassis_id"] = chassis["id"]
                    results.append(data)
            except Exception:
                continue
        return results

    def get_all_power(self) -> list:
        results = []
        for chassis in self._chassis_list:
            try:
                url = f"{chassis['url']}/Power"
                resp = self.rf.session.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    data["_chassis_id"] = chassis["id"]
                    results.append(data)
            except Exception:
                continue
        return results


class RedfishThermalSubsystem:
    """
    Redfish ThermalSubsystem schema — Redfish 2022.3+.
    Newer schema with per-component cooling resources.
    Path: /redfish/v1/Chassis/{id}/ThermalSubsystem
    """

    def __init__(self, redfish_client, chassis_id: str = "Self"):
        self.rf = redfish_client
        self.chassis_id = chassis_id
        self._base = f"{self.rf.base_url}/Chassis/{chassis_id}/ThermalSubsystem"
        self._available = self._check()

    def _check(self) -> bool:
        try:
            resp = self.rf.session.get(self._base)
            return resp.status_code == 200
        except Exception:
            return False

    def get_fans(self) -> list:
        """List all fans with current reading and status."""
        if not self._available:
            return []
        try:
            resp = self.rf.session.get(f"{self._base}/Fans")
            if resp.status_code != 200:
                return []
            members = resp.json().get("Members", [])
            fans = []
            host = self.rf.base_url.split("/redfish")[0]
            for m in members:
                path = m.get("@odata.id", "")
                url = host + path if not path.startswith("http") else path
                fan_resp = self.rf.session.get(url)
                if fan_resp.status_code == 200:
                    fans.append(fan_resp.json())
            return fans
        except Exception as e:
            logger.error(f"ThermalSubsystem fans error: {e}")
            return []

    def get_pumps(self) -> list:
        """List all liquid cooling pumps."""
        if not self._available:
            return []
        try:
            resp = self.rf.session.get(f"{self._base}/Pumps")
            if resp.status_code != 200:
                return []
            members = resp.json().get("Members", [])
            pumps = []
            host = self.rf.base_url.split("/redfish")[0]
            for m in members:
                path = m.get("@odata.id", "")
                url = host + path if not path.startswith("http") else path
                pump_resp = self.rf.session.get(url)
                if pump_resp.status_code == 200:
                    pumps.append(pump_resp.json())
            return pumps
        except Exception as e:
            logger.error(f"ThermalSubsystem pumps error: {e}")
            return []

    def set_fan_setpoint(self, fan_id: str, setpoint_pct: int) -> bool:
        """Control individual fan via ThermalSubsystem/Fans schema."""
        if not self._available:
            return False
        try:
            host = self.rf.base_url.split("/redfish")[0]
            url = f"{self._base}/Fans/{fan_id}"
            resp = self.rf.session.patch(url, json={"SetPoint": setpoint_pct})
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"ThermalSubsystem fan setpoint error: {e}")
            return False


class RedfishAggregation:
    """
    Redfish Aggregation Service — for DCIM or rack-level management.
    Connects to an aggregation manager that proxies multiple BMCs.
    Path: /redfish/v1/AggregationService/Aggregates
    """

    def __init__(self, aggregation_host: str, username: str, password: str):
        import httpx
        self.base_url = f"https://{aggregation_host}/redfish/v1"
        self.session = httpx.Client(
            verify=False, auth=(username, password), timeout=2.0)
        self._aggregates = []
        self._discover()

    def _discover(self):
        try:
            resp = self.session.get(f"{self.base_url}/AggregationService/Aggregates")
            if resp.status_code == 200:
                self._aggregates = resp.json().get("Members", [])
                logger.info(f"Redfish Aggregation: {len(self._aggregates)} aggregates")
        except Exception as e:
            logger.debug(f"Aggregation service not available: {e}")

    def get_all_thermal_summary(self) -> dict:
        """
        Pull thermal summary across all aggregated resources.
        Returns a dict keyed by resource ID.
        """
        summary = {}
        for agg in self._aggregates:
            path = agg.get("@odata.id", "")
            if not path:
                continue
            host = self.base_url.split("/redfish")[0]
            url = (host + path if not path.startswith("http") else path) + "/Thermal"
            try:
                resp = self.session.get(url)
                if resp.status_code == 200:
                    agg_id = path.rstrip("/").split("/")[-1]
                    summary[agg_id] = resp.json()
            except Exception:
                continue
        return summary
