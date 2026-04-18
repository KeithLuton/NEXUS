#!/usr/bin/env python3
"""
NEXUS Trial v3.0 - Quick Start Runner
Orchestrates the complete thermal prediction system end-to-end
"""

import argparse
import sys
import logging
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description="NEXUS Trial v3.0 Quick Start",
        epilog="Example: python quickstart.py --bmc-host 192.168.1.100 --bmc-user root --bmc-pass password123"
    )
    parser.add_argument("--bmc-host", required=True, help="BMC hostname or IP")
    parser.add_argument("--bmc-user", required=True, help="Redfish username")
    parser.add_argument("--bmc-pass", required=True, help="Redfish password")
    parser.add_argument("--binary", help="Override proprietary binary path", 
                       default="02_Proprietary_Engine/spigot_torch_LINUX_x86_64")
    parser.add_argument("--config", help="Override config path",
                       default="06_Configuration/chassis_map.json")
    
    args = parser.parse_args()
    
    # Validate paths
    if not Path(args.binary).exists():
        logger.error(f"Binary not found: {args.binary}")
        return 1
    
    if not Path(args.config).exists():
        logger.error(f"Config not found: {args.config}")
        return 1
    
    try:
        # Import NEXUS modules
        sys.path.insert(0, '03_Core_Logic')
        sys.path.insert(0, '04_Infrastructure')
        
        from nexus_orchestrator import NexusOrchestrator
        from workload_proxy_ingress import start_ingress
        from bmc_signal_poller import BMCSignalPoller
        from redfish_client import RedfishInterface
        import threading
        
        logger.info("="*60)
        logger.info("NEXUS Trial v3.0 - Thermal Prediction System")
        logger.info("="*60)
        
        # Initialize orchestrator
        logger.info(f"Initializing orchestrator...")
        logger.info(f"  Binary: {args.binary}")
        logger.info(f"  Config: {args.config}")
        logger.info(f"  BMC: {args.bmc_host}")
        
        orch = NexusOrchestrator(
            args.config,
            args.binary,
            args.bmc_host,
            args.bmc_user,
            args.bmc_pass
        )
        
        # Start BMC Signal Poller — pre-OS signal source
        # This is what makes NEXUS actually predictive.
        # Polls BMC power rails every 15ms, detects spikes before OS sees them.
        logger.info("Starting BMC Signal Poller (pre-OS signal source)...")
        redfish = RedfishInterface(args.bmc_host, args.bmc_user, args.bmc_pass)
        poller = BMCSignalPoller(redfish, orchestrator=orch)
        poller.start()

        # Start HTTP ingress server (secondary signal source — OS-level workload intent)
        logger.info("Starting workload ingress server on 0.0.0.0:8000...")
        ingress_thread = threading.Thread(
            target=start_ingress,
            args=(orch,),
            daemon=True
        )
        ingress_thread.start()
        
        time.sleep(1)
        
        logger.info("")
        logger.info("="*60)
        logger.info("NEXUS Orchestrator Running")
        logger.info("="*60)
        logger.info("Signal Sources:")
        logger.info("  [1] BMC Power Poller (pre-OS) — ACTIVE @ 15ms cycle")
        logger.info(f"      Polling: https://{args.bmc_host}/redfish/v1/Chassis/Self/Power")
        logger.info("  [2] HTTP Workload Ingress (OS-level) — ACTIVE @ :8000")
        logger.info("      POST http://localhost:8000/predict")
        logger.info("")
        logger.info("Monitoring:")
        logger.info("  Health:     http://localhost:8000/health")
        logger.info("  Statistics: http://localhost:8000/status")
        logger.info("")
        logger.info("To trigger a test workload in another terminal:")
        logger.info("  python 05_Testing_Tools/mock_workload_generator.py \\")
        logger.info("    --test mixed --duration 30")
        logger.info("")
        logger.info("Press Ctrl+C to stop")
        logger.info("="*60)
        
        # Keep running
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        try:
            poller.stop()
        except Exception:
            pass
        return 0
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
