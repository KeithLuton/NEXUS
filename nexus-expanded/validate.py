#!/usr/bin/env python3
"""
NEXUS Trial v3.0 - Pre-Deployment Validation Script
Validates binaries, configuration, and connectivity before deployment
"""

import os
import sys
import json
import subprocess
import argparse
import socket
from pathlib import Path

class Validator:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.errors = []
        self.warnings = []
        self.success = []
    
    def check(self, condition, success_msg, error_msg):
        if condition:
            self.success.append(success_msg)
            if self.verbose:
                print(f"✓ {success_msg}")
        else:
            self.errors.append(error_msg)
            print(f"✗ {error_msg}")
    
    def warn(self, condition, msg):
        if condition:
            self.warnings.append(msg)
            print(f"⚠ {msg}")
    
    def validate_binaries(self):
        print("\n=== Binary Validation ===")
        
        linux_binary = Path("02_Proprietary_Engine/spigot_torch_LINUX_x86_64")
        arm_binary = Path("02_Proprietary_Engine/spigot_torch_BMC_ARM64")
        windows_binary = Path("02_Proprietary_Engine/spigot_torch_WINDOWS_x64.exe")
        
        self.check(linux_binary.exists(), f"Linux x86_64 binary ({linux_binary.stat().st_size} bytes)", "Linux x86_64 binary not found")
        self.check(arm_binary.exists(), f"ARM64 binary ({arm_binary.stat().st_size} bytes)", "ARM64 binary not found")
        self.check(windows_binary.exists(), f"Windows x64 binary ({windows_binary.stat().st_size} bytes)", "Windows x64 binary not found")
        
        # Check executability on Unix
        if sys.platform != "win32":
            self.check(os.access(linux_binary, os.X_OK), "Linux binary is executable", "Linux binary is not executable")
            self.check(os.access(arm_binary, os.X_OK), "ARM binary is executable", "ARM binary is not executable")
    
    def validate_python_modules(self):
        print("\n=== Python Module Validation ===")
        
        modules = [
            ("03_Core_Logic/solver_wrapper.py", "Solver wrapper"),
            ("03_Core_Logic/nexus_orchestrator.py", "Orchestrator"),
            ("04_Infrastructure/redfish_client.py", "Redfish client"),
            ("05_Testing_Tools/workload_proxy_ingress.py", "Workload ingress"),
            ("05_Testing_Tools/mock_workload_generator.py", "Workload generator"),
        ]
        
        for path, name in modules:
            p = Path(path)
            self.check(p.exists(), f"{name} module found", f"{name} module not found at {path}")
            if p.exists():
                try:
                    with open(p, 'r') as f:
                        compile(f.read(), path, 'exec')
                    self.check(True, f"{name} syntax valid", "")
                except SyntaxError as e:
                    self.check(False, "", f"{name} has syntax error: {e}")
    
    def validate_config(self):
        print("\n=== Configuration Validation ===")
        
        config_file = Path("06_Configuration/chassis_map.json")
        self.check(config_file.exists(), "chassis_map.json found", "chassis_map.json not found")
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                self.check(True, "chassis_map.json is valid JSON", "")
                self.check('chassis_id' in config, "chassis_id defined", "chassis_id not in config")
                self.check('zones' in config, "zones array defined", "zones not in config")
                if 'zones' in config:
                    zone_count = len(config['zones'])
                    self.check(zone_count > 0, f"{zone_count} zones configured", f"No zones defined (need at least 1)")
            except json.JSONDecodeError as e:
                self.check(False, "", f"chassis_map.json JSON error: {e}")
    
    def validate_dependencies(self):
        print("\n=== Python Dependencies ===")
        
        required = ['fastapi', 'uvicorn', 'pydantic', 'httpx', 'requests']
        
        for pkg in required:
            try:
                __import__(pkg)
                self.check(True, f"{pkg} installed", "")
            except ImportError:
                self.check(False, "", f"{pkg} not installed (run: pip install -r requirements.txt)")
    
    def validate_connectivity(self, bmc_host=None):
        if not bmc_host:
            print("\n=== BMC Connectivity (Skipped) ===")
            print("(Pass --bmc-host to validate Redfish connectivity)")
            return
        
        print(f"\n=== BMC Connectivity Test ({bmc_host}) ===")
        
        # Test network connectivity
        try:
            socket.create_connection((bmc_host, 443), timeout=3)
            self.check(True, f"BMC reachable on {bmc_host}:443", "")
        except (socket.timeout, socket.error) as e:
            self.check(False, "", f"Cannot reach BMC at {bmc_host}:443: {e}")
    
    def report(self):
        print("\n" + "="*60)
        print(f"Validation Results: {len(self.success)} passed, {len(self.warnings)} warnings, {len(self.errors)} errors")
        print("="*60)
        
        if self.errors:
            print("\nCritical Issues:")
            for err in self.errors:
                print(f"  ✗ {err}")
            return False
        
        if self.warnings:
            print("\nWarnings:")
            for warn in self.warnings:
                print(f"  ⚠ {warn}")
        
        print("\n✓ All validations passed!")
        return True

def main():
    parser = argparse.ArgumentParser(description="NEXUS Trial v3.0 Validation")
    parser.add_argument("--bmc-host", help="BMC hostname/IP for connectivity test")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    validator = Validator(verbose=args.verbose)
    validator.validate_binaries()
    validator.validate_python_modules()
    validator.validate_config()
    validator.validate_dependencies()
    validator.validate_connectivity(args.bmc_host)
    
    success = validator.report()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
