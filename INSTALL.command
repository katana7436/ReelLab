#!/bin/bash
# Double-click to install ReelLab on a Mac (about 5-10 minutes). Everything stays in this folder.
cd "$(dirname "$0")"
bash ./install_mac.sh
echo; read -n 1 -s -r -p "Press any key to close"
