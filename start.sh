#!/usr/bin/env bash
# Start Menicka on a free port: ./start.sh
#
# Tries the port saved in .env (or 47823), then the next ones, until Docker
# manages to bind one. The chosen port is saved to .env, so plain
# `docker compose up/down/restart` keep using it.
set -euo pipefail
cd "$(dirname "$0")"

FIRST=${PORT:-$( (grep -E '^PORT=[0-9]+$' .env 2>/dev/null || echo PORT=47823) | tail -1 | cut -d= -f2)}
TRIES=${TRIES:-50}

port_busy() {  # something on this machine already accepts connections on the port
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

save_port() {
  if [ -f .env ] && grep -qE '^PORT=' .env; then
    sed -i.bak -E "s/^PORT=.*/PORT=$1/" .env && rm -f .env.bak
  else
    echo "PORT=$1" >> .env
  fi
}

echo "Building image..."
docker compose build
# Free our own old port first so it does not count as taken.
docker compose down --remove-orphans >/dev/null 2>&1 || true

port=$FIRST
for _ in $(seq 1 "$TRIES"); do
  if port_busy "$port"; then
    echo "Port $port is taken, trying $((port + 1))"
    port=$((port + 1))
    continue
  fi
  if out=$(PORT=$port docker compose up -d 2>&1); then
    save_port "$port"
    echo
    echo "Menicka is running: http://localhost:$port"
    echo "Logs: docker compose logs -f    Stop: docker compose down"
    exit 0
  fi
  if echo "$out" | grep -qiE 'already allocated|address already in use|bind'; then
    echo "Port $port is taken, trying $((port + 1))"
    docker compose down >/dev/null 2>&1 || true
    port=$((port + 1))
    continue
  fi
  echo "$out" >&2
  exit 1
done
echo "No free port found in $FIRST..$((FIRST + TRIES - 1))" >&2
exit 1
