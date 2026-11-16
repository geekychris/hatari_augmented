#!/bin/sh
# Start the ST DevBench: http://127.0.0.1:3520/ (dev page) and /arcade (the games).
#   tools/devbench/run.sh [--port N] [--games ../atari_st_games] [--hatari-port 7777] [--open]
exec python3 "$(dirname "$0")/devbench.py" "$@"
