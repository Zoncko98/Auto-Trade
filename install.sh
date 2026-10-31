#!/bin/sh
# Portable TrueNAS SCALE installation. Live brokerage orders stay disabled.
set -eu
cd "$(dirname "$0")"
if [ ! -f deploy/docker-compose.yml ]; then
  echo "Run from the repository root" >&2
  exit 1
fi
echo "Auto Trader setup — generated credentials stay outside Git"
echo "The installer builds ONLY the dashboard container."
python3 installer/setup.py --install
