#!/usr/bin/env python3
"""
NEXUS Trial v3.0 - Demo Mode
Standalone demo that proves NEXUS works without requiring a BMC.
Uses mock workload + solver wrapper only.
Safe to run, doesn't touch core infrastructure.
"""

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
    logger.info("=" * 70)
    logger.info("NEXUS Trial v3.0 - DEMO MODE")
    logger.info("=" * 70)
    logger.info("")
    logger.info("This demo proves NEXUS works WITHOUT requiring a BMC.")
    logger.info("It uses only the solver + mock workload generator.")
    logger.info("")
    
    # Validate binary exists
    binary_path = Path("02_Proprietary_Engine/spigot_torch_LINUX_x86_64")
    
    # Try to detect OS and use appropriate binary
    import platform
    if platform.system() == "Windows":
        binary_path = Path("02_Proprietary_Engine/spigot_torch_WINDOWS_x64.exe")
    elif platform.machine() == "aarch64":
        binary_path = Path("02_Proprietary_Engine/spigot_torch_BMC_ARM64")
    
    if not binary_path.exists():
        logger.error(f"Binary not found: {binary_path}")
        logger.error("Please extract NEXUS_TRIAL_V3.0.zip first")
        return 1
    
    try:
        # Import NEXUS modules
        sys.path.insert(0, '03_Core_Logic')
        sys.path.insert(0, '04_Infrastructure')
        sys.path.insert(0, '05_Testing_Tools')
        
        from demo_runner import run_demo
        
        logger.info("Starting demo...\n")
        run_demo(str(binary_path))
        
        return 0
    
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure you're in the NEXUS_TRIAL_V3.0 directory")
        return 1
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
