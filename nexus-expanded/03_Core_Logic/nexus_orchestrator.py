import json
import time
import logging
from solver_wrapper import SpigotTorchWrapper
from redfish_client import RedfishInterface

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class NexusOrchestrator:
    """
    Central nervous system for predictive thermal management.
    Orchestrates the control loop: Intent -> Solve -> Actuate.
    """
    def __init__(self, config_path, binary_path, bmc_host, bmc_user, bmc_pass):
        """
        Initialize the orchestrator.
        
        Args:
            config_path: Path to chassis_map.json
            binary_path: Path to the proprietary spigot_torch binary
            bmc_host: BMC hostname or IP
            bmc_user: Redfish username
            bmc_pass: Redfish password
        """
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
            logger.info(f"Loaded config: {config_path}")
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_path}")
            raise
        
        self.solver = SpigotTorchWrapper(binary_path)
        self.redfish = RedfishInterface(bmc_host, bmc_user, bmc_pass)
        self.loop_times = []

    def process_intent(self, intent_data):
        """
        Main control loop: execute once per workload intent.
        
        Args:
            intent_data: dict with keys 'cpu_zones', 'gpu_zones', 'mem_load'
        
        Returns:
            dict with execution metadata (latency, actuation count)
        """
        loop_start = time.time()
        
        # 1. Build the 32-float workload vector
        vector = [0.0] * 32
        
        # Populate CPU zones (slots 0-3)
        cpu_zones = intent_data.get('cpu_zones', [0.0] * 4)
        for i, val in enumerate(cpu_zones[:4]):
            vector[i] = float(val)
        
        # Populate GPU zones (slots 4-7)
        gpu_zones = intent_data.get('gpu_zones', [0.0] * 4)
        for i, val in enumerate(gpu_zones[:4]):
            vector[4 + i] = float(val)
        
        # Populate memory load (slot 8)
        vector[8] = float(intent_data.get('mem_load', 0.0))
        
        # Remaining slots can be reserved for future use
        
        # 2. Solve the thermal prediction (Proprietary Black Box)
        solver_start = time.time()
        prediction = self.solver.solve(vector)
        solver_time = (time.time() - solver_start) * 1000
        
        if not prediction:
            logger.error("Solver returned None")
            return {"status": "error", "latency_ms": (time.time() - loop_start) * 1000}
        
        # 3. Actuate: Send predictions to Redfish controls
        actuation_count = 0
        for zone in self.config.get('zones', []):
            zone_id = zone.get('zone_id')
            actuators = zone.get('actuators', [])
            
            if zone_id < len(prediction):
                predicted_temp = prediction[zone_id]
                
                # Map temperature prediction to PWM percentage (0-100)
                # Formula: pwm = (temp / 100) * 100, clamped to [20, 100]
                pwm_setpoint = min(max(int(predicted_temp * 2.5), 20), 100)
                
                for actuator in actuators:
                    redfish_id = actuator.get('redfish_id')
                    chassis_id = self.config.get('chassis_id', 'Self')
                    
                    result = self.redfish.patch_control(chassis_id, redfish_id, pwm_setpoint)
                    if result:
                        actuation_count += 1
                        logger.debug(f"Zone {zone_id} -> {redfish_id}: {pwm_setpoint}%")
        
        loop_time = (time.time() - loop_start) * 1000
        self.loop_times.append(loop_time)
        
        result = {
            "status": "success",
            "solver_time_ms": solver_time,
            "total_loop_ms": loop_time,
            "actuations": actuation_count,
            "zones_processed": len(self.config.get('zones', []))
        }
        
        logger.info(f"Loop complete: {loop_time:.2f}ms (solver: {solver_time:.2f}ms, actuations: {actuation_count})")
        return result

    def get_stats(self):
        """Return performance statistics."""
        if not self.loop_times:
            return {"min_ms": 0, "max_ms": 0, "avg_ms": 0, "loops": 0}
        
        return {
            "min_ms": min(self.loop_times),
            "max_ms": max(self.loop_times),
            "avg_ms": sum(self.loop_times) / len(self.loop_times),
            "loops": len(self.loop_times)
        }
