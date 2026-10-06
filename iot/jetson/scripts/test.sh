#!/usr/bin/env bash
# SDK 단위 시험. 브로커도 Pi 도 없이 돈다.
#
#   ./scripts/test.sh              전부
#   ./scripts/test.sh -k stream    이름으로 고르기

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

run_py -m pytest tests/ -q "$@"
