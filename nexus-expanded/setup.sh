#!/bin/bash
# NEXUS Trial Package Installer
# Sets up Python dependencies and validates binary platforms

echo "=== NEXUS Trial v3.0 Setup ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Install Python 3.8+ and try again."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✓ Python $PYTHON_VERSION detected"

# Install dependencies
echo ""
echo "Installing Python dependencies..."
python3 -m pip install -q -r requirements.txt
echo "✓ Dependencies installed"

# Verify binaries
echo ""
echo "Validating proprietary binaries..."

if [ -f "02_Proprietary_Engine/spigot_torch_LINUX_x86_64" ]; then
    echo "✓ Linux x86_64 binary (667K)"
    chmod +x 02_Proprietary_Engine/spigot_torch_LINUX_x86_64
fi

if [ -f "02_Proprietary_Engine/spigot_torch_BMC_ARM64" ]; then
    echo "✓ BMC ARM64 binary (587K)"
    chmod +x 02_Proprietary_Engine/spigot_torch_BMC_ARM64
fi

if [ -f "02_Proprietary_Engine/spigot_torch_WINDOWS_x64.exe" ]; then
    echo "✓ Windows x64 binary (40K)"
fi

# Verify Python modules
echo ""
echo "Validating open-source modules..."
MODULES=("03_Core_Logic/solver_wrapper.py" "03_Core_Logic/nexus_orchestrator.py" "04_Infrastructure/redfish_client.py" "05_Testing_Tools/workload_proxy_ingress.py" "05_Testing_Tools/mock_workload_generator.py" "06_Configuration/chassis_map.json")

for module in "${MODULES[@]}"; do
    if [ -f "$module" ]; then
        echo "✓ $module"
    else
        echo "✗ $module (MISSING)"
    fi
done

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit 06_Configuration/chassis_map.json with your Redfish control IDs"
echo "2. Run: python3 03_Core_Logic/nexus_orchestrator.py --help"
echo ""
echo "For detailed instructions, see: 01_Documentation/README.md"
