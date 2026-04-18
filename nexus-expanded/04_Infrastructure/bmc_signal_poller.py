"""
NEXUS Trial v3.0 - BMC Signal Poller
Pre-OS Signal Source: Detects workload intent from BMC power rail telemetry
BEFORE the OS thermal sensors or scheduler reports anything.

Architecture:
    BMC Power Rails (Redfish) → Delta Detection → Workload Vector → Orchestrator
    
This is what makes NEXUS actually predictive. Without this, the system is
just reactive with extra steps. With this, fans move before heat exists.

Poll cycle: 10-20ms (faster than any OS thermal event)
Signal source: Redfish /Chassis/Self/Power (out-of-band, OS-independent)
"""

import time
import logging
import threading
from collections import deque
from redfish_client import RedfishInterface

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ─────────────────────────────────────────────
# Tuning Constants
# ─────────────────────────────────────────────

POLL_INTERVAL_S       = 0.015   # 15ms poll cycle — faster than OS thermal events
DELTA_WINDOW          = 5       # Number of samples to average for baseline
SPIKE_THRESHOLD_W     = 50.0    # Watts delta to classify as a workload spike
CPU_POWER_MAX_W       = 400.0   # Expected TDP ceiling for normalization (per socket)
GPU_POWER_MAX_W       = 700.0   # Expected TDP ceiling for normalization (per GPU)
MEM_POWER_MAX_W       = 50.0    # Expected TDP ceiling for normalization (memory)
SMOOTHING_ALPHA       = 0.3     # EMA smoothing factor (lower = smoother, more lag)


class PowerReading:
    """Parsed snapshot of BMC power telemetry at one point in time."""

    def __init__(self):
        self.timestamp      = 0.0
        self.total_watts    = 0.0
        self.cpu_watts      = [0.0, 0.0, 0.0, 0.0]   # Up to 4 CPU sockets
        self.gpu_watts      = [0.0, 0.0, 0.0, 0.0]   # Up to 4 GPU cards
        self.mem_watts      = 0.0
        self.raw            = {}

    @classmethod
    def from_redfish(cls, power_json):
        """
        Parse a Redfish Power resource into a PowerReading.
        Handles iLO, iDRAC, OpenBMC, and generic DSP0266 layouts.
        """
        reading = cls()
        reading.timestamp = time.time()

        if not power_json:
            return reading

        reading.raw = power_json

        # ── Total chassis power ──────────────────────────────────────────
        # PowerControl[0].PowerConsumedWatts is the standard location
        power_controls = power_json.get("PowerControl", [])
        if power_controls:
            reading.total_watts = float(
                power_controls[0].get("PowerConsumedWatts", 0.0)
            )

        # ── Per-component power via PowerSupplies or Voltages ────────────
        # Vendors expose component power differently. We try common patterns.

        # Pattern 1: Labeled PowerControl entries (OpenBMC, some iDRAC)
        for entry in power_controls:
            name = entry.get("Name", "").upper()
            watts = float(entry.get("PowerConsumedWatts", 0.0))

            if "CPU" in name or "PROCESSOR" in name:
                # Extract socket index if present: "CPU 0", "Processor 1", etc.
                idx = _extract_index(name, max_idx=3)
                reading.cpu_watts[idx] = watts

            elif "GPU" in name or "ACCELERATOR" in name:
                idx = _extract_index(name, max_idx=3)
                reading.gpu_watts[idx] = watts

            elif "MEM" in name or "DIMM" in name:
                reading.mem_watts = watts

        # Pattern 2: Voltages array with current/power data (iLO style)
        for v in power_json.get("Voltages", []):
            name = v.get("Name", "").upper()
            amps = float(v.get("ReadingAmps", 0.0))
            volts = float(v.get("ReadingVolts", 0.0))
            watts = amps * volts

            if "CPU" in name:
                idx = _extract_index(name, max_idx=3)
                if reading.cpu_watts[idx] == 0.0:   # Don't overwrite Pattern 1
                    reading.cpu_watts[idx] = watts
            elif "GPU" in name:
                idx = _extract_index(name, max_idx=3)
                if reading.gpu_watts[idx] == 0.0:
                    reading.gpu_watts[idx] = watts
            elif "MEM" in name:
                if reading.mem_watts == 0.0:
                    reading.mem_watts = watts

        # ── Fallback: decompose total power if component data is missing ─
        # If vendor doesn't expose per-component power, estimate from total.
        # This is a worst-case fallback — real hardware should have labels.
        if all(w == 0.0 for w in reading.cpu_watts) and reading.total_watts > 0:
            # Rough heuristic: CPU ~40%, GPU ~50%, Mem ~10% of total
            estimated_cpu = reading.total_watts * 0.40 / 2   # Split across 2 sockets
            estimated_gpu = reading.total_watts * 0.50 / 2   # Split across 2 GPUs
            estimated_mem = reading.total_watts * 0.10
            reading.cpu_watts[0] = estimated_cpu
            reading.cpu_watts[1] = estimated_cpu
            reading.gpu_watts[0] = estimated_gpu
            reading.gpu_watts[1] = estimated_gpu
            reading.mem_watts    = estimated_mem
            logger.debug("Using total-power decomposition fallback (no labeled components)")

        return reading


def _extract_index(name: str, max_idx: int = 3) -> int:
    """Pull the first digit from a label like 'CPU 2' or 'GPU_CARD_1'."""
    for ch in name:
        if ch.isdigit():
            return min(int(ch), max_idx)
    return 0


class BMCSignalPoller:
    """
    Polls BMC power telemetry on a tight loop and converts delta spikes
    into normalized workload intent vectors for the NEXUS orchestrator.

    This runs in its own daemon thread. The orchestrator calls
    get_latest_intent() at any time to get the most recent pre-OS signal.

    Usage:
        poller = BMCSignalPoller(redfish_client, orchestrator)
        poller.start()
        # ... poller feeds orchestrator automatically in background
        poller.stop()
    """

    def __init__(self, redfish: RedfishInterface, orchestrator=None):
        self.redfish       = redfish
        self.orchestrator  = orchestrator

        self._running      = False
        self._thread       = None
        self._lock         = threading.Lock()

        # Rolling window of recent readings for baseline calculation
        self._history      = deque(maxlen=DELTA_WINDOW)

        # Latest smoothed intent vector (32 floats, 0.0–1.0)
        self._latest_intent = [0.0] * 32

        # EMA state for smoothing
        self._ema_cpu      = [0.0] * 4
        self._ema_gpu      = [0.0] * 4
        self._ema_mem      = 0.0

        # Stats
        self.poll_count    = 0
        self.spike_count   = 0
        self.last_poll_ms  = 0.0

    # ─────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────

    def start(self):
        """Start the background polling thread."""
        if self._running:
            logger.warning("Poller already running")
            return

        self._running = True
        self._thread  = threading.Thread(
            target=self._poll_loop,
            name="BMCSignalPoller",
            daemon=True          # Dies with main process — no cleanup required
        )
        self._thread.start()
        logger.info(
            f"BMC Signal Poller started — poll interval: {POLL_INTERVAL_S*1000:.0f}ms, "
            f"spike threshold: {SPIKE_THRESHOLD_W}W"
        )

    def stop(self):
        """Stop the background polling thread gracefully."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        logger.info(
            f"BMC Signal Poller stopped — "
            f"{self.poll_count} polls, {self.spike_count} spikes detected"
        )

    def get_latest_intent(self) -> list:
        """
        Return the most recent normalized workload intent vector (32 floats).
        Thread-safe. Call from orchestrator or any consumer at any time.
        """
        with self._lock:
            return list(self._latest_intent)

    def get_stats(self) -> dict:
        """Return poller performance statistics."""
        return {
            "poll_count"    : self.poll_count,
            "spike_count"   : self.spike_count,
            "last_poll_ms"  : self.last_poll_ms,
            "poll_interval_ms": POLL_INTERVAL_S * 1000,
        }

    # ─────────────────────────────────────────
    # Internal Poll Loop
    # ─────────────────────────────────────────

    def _poll_loop(self):
        """
        Main loop: poll BMC → parse → detect delta → build intent → actuate.
        Runs every POLL_INTERVAL_S seconds in a daemon thread.
        """
        while self._running:
            loop_start = time.time()

            try:
                self._tick()
            except Exception as e:
                logger.error(f"Poll tick error: {e}")

            # Sleep for remainder of poll interval (compensates for execution time)
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, POLL_INTERVAL_S - elapsed)
            time.sleep(sleep_time)

            self.last_poll_ms = (time.time() - loop_start) * 1000
            self.poll_count  += 1

    def _tick(self):
        """Single poll cycle: read → parse → smooth → detect spike → dispatch."""

        # ── 1. Read BMC power telemetry (out-of-band, OS-independent) ────
        raw = self.redfish.get_power_metrics()
        if raw is None:
            logger.debug("BMC power read returned None — skipping tick")
            return

        reading = PowerReading.from_redfish(raw)

        # ── 2. Build baseline from rolling history ────────────────────────
        baseline = self._get_baseline()
        self._history.append(reading)

        # ── 3. Compute EMA-smoothed normalized load per component ─────────
        for i in range(4):
            raw_cpu_load = min(reading.cpu_watts[i] / max(CPU_POWER_MAX_W, 1.0), 1.0)
            raw_gpu_load = min(reading.gpu_watts[i] / max(GPU_POWER_MAX_W, 1.0), 1.0)
            self._ema_cpu[i] = _ema(self._ema_cpu[i], raw_cpu_load, SMOOTHING_ALPHA)
            self._ema_gpu[i] = _ema(self._ema_gpu[i], raw_gpu_load, SMOOTHING_ALPHA)

        raw_mem_load = min(reading.mem_watts / max(MEM_POWER_MAX_W, 1.0), 1.0)
        self._ema_mem = _ema(self._ema_mem, raw_mem_load, SMOOTHING_ALPHA)

        # ── 4. Detect power spike vs rolling baseline ─────────────────────
        delta_watts = reading.total_watts - baseline
        is_spike    = abs(delta_watts) >= SPIKE_THRESHOLD_W

        if is_spike:
            self.spike_count += 1
            direction = "▲ spike" if delta_watts > 0 else "▼ drop"
            logger.info(
                f"Pre-OS signal: {direction} {abs(delta_watts):.1f}W detected "
                f"(total: {reading.total_watts:.1f}W, baseline: {baseline:.1f}W)"
            )

        # ── 5. Build 32-float intent vector ───────────────────────────────
        # Slots 0–3:  CPU zones (normalized 0.0–1.0)
        # Slots 4–7:  GPU zones (normalized 0.0–1.0)
        # Slot  8:    Memory load (normalized 0.0–1.0)
        # Slot  9:    Total power normalized (system-level signal)
        # Slots 10–11: Delta magnitude and direction
        # Slots 12–31: Reserved (zero-padded)

        intent = [0.0] * 32

        for i in range(4):
            intent[i]     = self._ema_cpu[i]   # CPU zones
            intent[4 + i] = self._ema_gpu[i]   # GPU zones

        intent[8]  = self._ema_mem
        intent[9]  = min(reading.total_watts / max(CPU_POWER_MAX_W * 2 + GPU_POWER_MAX_W * 2, 1.0), 1.0)
        intent[10] = min(abs(delta_watts) / max(SPIKE_THRESHOLD_W * 4, 1.0), 1.0)   # Delta magnitude
        intent[11] = 1.0 if delta_watts > 0 else 0.0                                # Spike direction

        # ── 6. Store latest intent (thread-safe) ──────────────────────────
        with self._lock:
            self._latest_intent = intent

        # ── 7. Feed orchestrator directly on spike (pre-OS actuation) ─────
        # On a spike we don't wait — we push immediately.
        # On steady state we still update so the orchestrator has current data.
        if self.orchestrator and (is_spike or self.poll_count % 10 == 0):
            intent_data = {
                "cpu_zones" : list(intent[0:4]),
                "gpu_zones" : list(intent[4:8]),
                "mem_load"  : intent[8],
            }
            self.orchestrator.process_intent(intent_data)

            if is_spike:
                logger.info(
                    f"  → Dispatched to orchestrator BEFORE OS thermal event "
                    f"(cpu: {[f'{x:.2f}' for x in intent[0:4]]}, "
                    f"gpu: {[f'{x:.2f}' for x in intent[4:8]]}, "
                    f"mem: {intent[8]:.2f})"
                )

    def _get_baseline(self) -> float:
        """Rolling average of total_watts over recent history window."""
        if not self._history:
            return 0.0
        return sum(r.total_watts for r in self._history) / len(self._history)


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _ema(prev: float, new: float, alpha: float) -> float:
    """Exponential moving average. alpha=1.0 = no smoothing."""
    return alpha * new + (1.0 - alpha) * prev


# ─────────────────────────────────────────────
# Standalone test (no orchestrator needed)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    )

    parser = argparse.ArgumentParser(description="NEXUS BMC Signal Poller — standalone test")
    parser.add_argument("--bmc-host", required=True,  help="BMC IP or hostname")
    parser.add_argument("--bmc-user", default="root", help="Redfish username")
    parser.add_argument("--bmc-pass", required=True,  help="Redfish password")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    args = parser.parse_args()

    redfish = RedfishInterface(args.bmc_host, args.bmc_user, args.bmc_pass)
    poller  = BMCSignalPoller(redfish, orchestrator=None)   # No orchestrator in test mode

    logger.info("=" * 60)
    logger.info("BMC Signal Poller — Standalone Test")
    logger.info(f"Target: {args.bmc_host} | Duration: {args.duration}s")
    logger.info("Watching for pre-OS power spikes...")
    logger.info("=" * 60)

    poller.start()

    try:
        for _ in range(args.duration):
            time.sleep(1.0)
            intent = poller.get_latest_intent()
            stats  = poller.get_stats()
            logger.info(
                f"Intent → CPU: {[f'{x:.2f}' for x in intent[0:4]]} | "
                f"GPU: {[f'{x:.2f}' for x in intent[4:8]]} | "
                f"Mem: {intent[8]:.2f} | "
                f"Polls: {stats['poll_count']} | Spikes: {stats['spike_count']} | "
                f"Loop: {stats['last_poll_ms']:.1f}ms"
            )
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()
        logger.info("Test complete.")
