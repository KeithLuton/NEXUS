import requests
import time
import json
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def trigger_cpu_burst(url, intensity=0.99, duration_sec=10):
    """Simulate a CPU workload burst."""
    logger.info(f"Triggering CPU burst (intensity={intensity}, duration={duration_sec}s)")
    
    payload = {
        "cpu_zones": [intensity, intensity, intensity, intensity],
        "gpu_zones": [0.1, 0.1, 0.1, 0.1],
        "mem_load": 0.3
    }
    
    start = time.time()
    while time.time() - start < duration_sec:
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.info(f"✓ Sent CPU intent: {response.json()}")
            else:
                logger.warning(f"Response: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send intent: {e}")
        
        time.sleep(1)

def trigger_gpu_burst(url, intensity=0.99, duration_sec=10):
    """Simulate a GPU workload burst."""
    logger.info(f"Triggering GPU burst (intensity={intensity}, duration={duration_sec}s)")
    
    payload = {
        "cpu_zones": [0.1, 0.1, 0.1, 0.1],
        "gpu_zones": [intensity, intensity, intensity, intensity],
        "mem_load": 0.5
    }
    
    start = time.time()
    while time.time() - start < duration_sec:
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.info(f"✓ Sent GPU intent: {response.json()}")
            else:
                logger.warning(f"Response: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send intent: {e}")
        
        time.sleep(1)

def trigger_mixed_workload(url, duration_sec=30):
    """Simulate a realistic mixed workload."""
    logger.info(f"Triggering mixed workload (duration={duration_sec}s)")
    
    start = time.time()
    phase = 0
    
    while time.time() - start < duration_sec:
        elapsed = time.time() - start
        
        # Phase 0: Low load
        if elapsed < 10:
            payload = {
                "cpu_zones": [0.2, 0.2, 0.2, 0.2],
                "gpu_zones": [0.1, 0.1, 0.1, 0.1],
                "mem_load": 0.2
            }
        # Phase 1: CPU spike
        elif elapsed < 20:
            payload = {
                "cpu_zones": [0.95, 0.95, 0.95, 0.95],
                "gpu_zones": [0.1, 0.1, 0.1, 0.1],
                "mem_load": 0.5
            }
        # Phase 2: GPU spike
        else:
            payload = {
                "cpu_zones": [0.2, 0.2, 0.2, 0.2],
                "gpu_zones": [0.90, 0.90, 0.90, 0.90],
                "mem_load": 0.6
            }
        
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.info(f"✓ Phase {phase}: {response.json()['status']}")
            phase = int(elapsed / 10)
        except Exception as e:
            logger.error(f"Request failed: {e}")
        
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEXUS Mock Workload Generator")
    parser.add_argument("--url", default="http://localhost:8000/predict", help="NEXUS ingress URL")
    parser.add_argument("--test", choices=["cpu", "gpu", "mixed"], default="mixed", help="Test type")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds")
    parser.add_argument("--intensity", type=float, default=0.99, help="Workload intensity (0.0-1.0)")
    
    args = parser.parse_args()
    
    logger.info(f"NEXUS Workload Generator v3.0")
    logger.info(f"Target: {args.url}")
    logger.info(f"Test: {args.test}")
    
    if args.test == "cpu":
        trigger_cpu_burst(args.url, args.intensity, args.duration)
    elif args.test == "gpu":
        trigger_gpu_burst(args.url, args.intensity, args.duration)
    else:
        trigger_mixed_workload(args.url, args.duration)
    
    logger.info("Workload test complete.")
