#!/bin/sh
# Live battery for realm-java-code: every view by name, then exact reconciliation against the
# jar itself, read here with Python's zipfile and a class-file reader (tests/classfile.py).
#
#   APPLIANCE=http://127.0.0.1:8080 AUTH=user:pass sh tests/verify.sh
#
# The realm reads a jar it ships (data/jars/spring-core-6.2.18.jar), so the battery needs no
# source key. Its last line on success is exactly `ALL CHECKS PASS`; any failure exits non-zero.
set -e
cd "$(dirname "$0")/.."
: "${AUTH:?set AUTH=user:pass for the target appliance}"
# -B: no __pycache__ beside the sources, so a run leaves the checkout exactly as it found it.
APPLIANCE="${APPLIANCE:-http://127.0.0.1:8080}" exec python3 -B tests/verify.py
