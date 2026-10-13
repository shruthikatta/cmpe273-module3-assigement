#!/usr/bin/env bash
# Runs every scenario for both versions and prints the results.
# Usage: ./scripts/demo.sh            (from the repo root, with .venv set up)
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
LOGS=evidence/logs
mkdir -p "$LOGS"

PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null; done; wait 2>/dev/null; }
trap cleanup EXIT

start() {  # start <logfile> <env...> -- <cmd...>
  local log=$1; shift
  env "$@" > "$log" 2>&1 &
  LAST_PID=$!
  PIDS+=("$LAST_PID")
}

wait_http() { for _ in $(seq 1 50); do curl -s -o /dev/null "$1" && return; sleep 0.1; done; }
wait_port() { for _ in $(seq 1 50); do nc -z localhost "$1" 2>/dev/null && return; sleep 0.1; done; }

run() { echo; echo "\$ $*"; eval "$@"; echo; }

order() {  # order <port> <json>
  curl -s -w '\nHTTP %{http_code}  (%{time_total}s)\n' -X POST "http://localhost:$1/orders" \
    -H 'Content-Type: application/json' -d "$2"
}

echo "################ REST VERSION ################"
start "$LOGS/rest_inventory.log" PYTHONUNBUFFERED=1 $PY rest/inventory_service.py
INV=$LAST_PID
start "$LOGS/rest_order.log" PYTHONUNBUFFERED=1 $PY rest/order_service.py
ORDER_REST=$LAST_PID
wait_http http://localhost:8000/health; wait_port 8001

echo "== Success =="
run "curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8001/inventory/check -H 'Content-Type: application/json' -d '{\"item_id\":\"apple\",\"quantity\":3}'"
run "order 8000 '{\"item_id\":\"apple\",\"quantity\":3}'"
echo "== Insufficient stock / unknown item / bad input =="
run "order 8000 '{\"item_id\":\"laptop\",\"quantity\":5}'"
run "order 8000 '{\"item_id\":\"unicorn\",\"quantity\":1}'"
run "order 8000 '{\"item_id\":\"apple\",\"quantity\":0}'"

echo "== Timeout: restart Inventory with a 5s delay (Order timeout = 2s) =="
kill $INV; wait $INV 2>/dev/null
start "$LOGS/rest_inventory_slow.log" PYTHONUNBUFFERED=1 INVENTORY_DELAY_SECONDS=5 $PY rest/inventory_service.py
wait_port 8001
run "order 8000 '{\"item_id\":\"apple\",\"quantity\":3}'"
echo "== Order Service still running after the timeout =="
run "ps -p $ORDER_REST -o pid=,command="
run "curl -s -w '\nHTTP %{http_code}\n' http://localhost:8000/health"
echo "== Remove the delay; the SAME Order Service process ($ORDER_REST) serves new orders =="
kill $LAST_PID; wait $LAST_PID 2>/dev/null
start "$LOGS/rest_inventory_recovered.log" PYTHONUNBUFFERED=1 $PY rest/inventory_service.py
wait_port 8001
run "order 8000 '{\"item_id\":\"banana\",\"quantity\":1}'"
run "ps -p $ORDER_REST -o pid=,command="
cleanup; PIDS=()

echo "################ gRPC VERSION ################"
start "$LOGS/grpc_inventory.log" PYTHONUNBUFFERED=1 $PY grpc_version/inventory_server.py
INV=$LAST_PID
start "$LOGS/grpc_order.log" PYTHONUNBUFFERED=1 $PY grpc_version/order_service.py
ORDER_GRPC=$LAST_PID
wait_http http://localhost:8002/health; wait_port 50051

echo "== Success =="
run "$PY grpc_version/client.py apple 3"
run "order 8002 '{\"item_id\":\"apple\",\"quantity\":3}'"
echo "== Insufficient stock / unknown item / bad input =="
run "$PY grpc_version/client.py laptop 5"
run "order 8002 '{\"item_id\":\"laptop\",\"quantity\":5}'"
run "order 8002 '{\"item_id\":\"unicorn\",\"quantity\":1}'"
run "order 8002 '{\"item_id\":\"apple\",\"quantity\":0}'"

echo "== Deadline: restart Inventory with a 5s delay (Order deadline = 2s) =="
kill $INV; wait $INV 2>/dev/null
start "$LOGS/grpc_inventory_slow.log" PYTHONUNBUFFERED=1 INVENTORY_DELAY_SECONDS=5 $PY grpc_version/inventory_server.py
wait_port 50051
run "$PY grpc_version/client.py apple 3 2"
run "order 8002 '{\"item_id\":\"apple\",\"quantity\":3}'"
echo "== Order Service still running after the deadline failure =="
run "ps -p $ORDER_GRPC -o pid=,command="
run "curl -s -w '\nHTTP %{http_code}\n' http://localhost:8002/health"
echo "== Remove the delay; the SAME Order Service process ($ORDER_GRPC) serves new orders =="
sleep 3  # let the slow server finish logging its delayed requests
kill $LAST_PID; wait $LAST_PID 2>/dev/null
start "$LOGS/grpc_inventory_recovered.log" PYTHONUNBUFFERED=1 $PY grpc_version/inventory_server.py
wait_port 50051
run "order 8002 '{\"item_id\":\"banana\",\"quantity\":1}'"
run "ps -p $ORDER_GRPC -o pid=,command="
cleanup; PIDS=()
for f in "$LOGS"/*.log; do perl -pi -e 's/\e\[[0-9;]*m//g' "$f"; done
