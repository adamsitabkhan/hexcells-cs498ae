#!/bin/bash
# setup_env.sh
# Run this script after cloning the repository to set up the reference modules.

echo "Initializing git submodules..."
git submodule update --init

echo "Applying PyQt5 patch to sixcells..."
cd external/sixcells || exit
# Check if patch is already applied
if ! git apply --check ../../sixcells-pyqt5.patch 2>/dev/null; then
    echo "Patch already applied or invalid."
else
    git apply ../../sixcells-pyqt5.patch
    echo "Successfully patched sixcells for PyQt5 compatibility."
fi
cd ../..

echo "Setup complete!"
