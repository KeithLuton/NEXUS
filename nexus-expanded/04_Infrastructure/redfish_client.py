import httpx
import logging

logger = logging.getLogger(__name__)

class RedfishInterface:
    """
    Standard Redfish Interface (DSP0266).
    Handles secure communication with any compliant BMC (Redfish 1.6+).
    Vendor-agnostic: works with IPMI, OpenBMC, iLO, iDRAC, etc.
    """
    def __init__(self, host, username, password, verify_ssl=False):
        """
        Initialize Redfish client.
        
        Args:
            host: BMC hostname or IP
            username: Redfish API username
            password: Redfish API password
            verify_ssl: SSL certificate verification (typically False for test/trial)
        """
        self.host = host
        self.base_url = f"https://{host}/redfish/v1"
        # Persistent session avoids handshake overhead on every control loop tick
        self.session = httpx.Client(
            verify=verify_ssl,
            auth=(username, password),
            timeout=0.1  # 100ms timeout for Redfish calls
        )
        logger.info(f"Redfish interface initialized for {host}")

    def get_thermal_sensors(self):
        """
        Pulls current thermal sensor readings for baseline comparison.
        Returns the full Thermal resource from Redfish.
        """
        try:
            url = f"{self.base_url}/Chassis/Self/Thermal"
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to read thermal sensors: {e}")
            return None

    def patch_control(self, chassis_id, control_id, setpoint):
        """
        Sends a predictive control command to a fan or pump actuator.
        Standard Redfish PATCH to Controls endpoint.
        
        Args:
            chassis_id: Redfish Chassis ID (e.g., "Self" or "1")
            control_id: Redfish Control ID (e.g., "Fan1", "Pump_Zone_A")
            setpoint: Target setpoint (typically 0-100 for PWM %)
        
        Returns:
            HTTP status code, or None on error
        """
        try:
            path = f"{self.base_url}/Chassis/{chassis_id}/Controls/{control_id}"
            payload = {"SetPoint": int(setpoint)}
            response = self.session.patch(path, json=payload)
            response.raise_for_status()
            logger.debug(f"Updated {control_id} to {setpoint}: {response.status_code}")
            return response.status_code
        except Exception as e:
            logger.error(f"Failed to update {control_id}: {e}")
            return None

    def get_power_metrics(self):
        """
        Reads current power consumption from Redfish (for workload correlation).
        """
        try:
            url = f"{self.base_url}/Chassis/Self/Power"
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to read power metrics: {e}")
            return None
