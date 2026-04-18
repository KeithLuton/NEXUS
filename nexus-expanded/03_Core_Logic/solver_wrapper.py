import subprocess
import os
import struct
import time

class SpigotTorchWrapper:
    """
    Wrapper for the proprietary SPIGOT_TORCH v3.0 kernel.
    Handles binary communication: sends 32 floats (128 bytes), receives 32 floats.
    """
    def __init__(self, binary_path):
        self.binary_path = binary_path
        if not os.path.exists(binary_path):
            raise FileNotFoundError(f"Proprietary Kernel not found at {binary_path}")
        # Make executable
        os.chmod(binary_path, 0o755)

    def solve(self, workload_vector):
        """
        Sends 32 floats to the C binary and gets 32 floats back.
        Latency target: <15ms.
        
        Args:
            workload_vector: list of 32 floats representing intent (0.0-1.0)
        
        Returns:
            tuple of 32 floats representing thermal predictions, or None on error
        """
        if len(workload_vector) != 32:
            raise ValueError(f"Expected 32 floats, got {len(workload_vector)}")
        
        # Pack 32 floats into 128 raw bytes
        input_data = struct.pack('f' * 32, *workload_vector)
        
        process = subprocess.Popen(
            [self.binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        try:
            # Atomic I/O for deterministic speed
            stdout, stderr = process.communicate(input=input_data, timeout=0.020)
            
            if process.returncode != 0 and process.returncode != 141:  # 141 = broken pipe
                print(f"Solver Error (code {process.returncode}): {stderr.decode()}")
                return None
            
            # Unpack 128 bytes back into 32 floats
            if len(stdout) == 128:
                return struct.unpack('f' * 32, stdout)
            else:
                print(f"Unexpected output size: {len(stdout)} bytes (expected 128)")
                return None
                
        except subprocess.TimeoutExpired:
            process.kill()
            print("Solver timeout (exceeded 20ms)")
            return None
        except Exception as e:
            print(f"Solver exception: {e}")
            return None
