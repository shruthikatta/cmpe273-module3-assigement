# CMPE 273 – Module 3: REST & gRPC Service Contracts

The same **Order → Inventory** interaction implemented twice in Python:

| | Order Service | Inventory Service | Order → Inventory | Failure guard |
|---|---|---|---|---|
| **REST** | `rest/order_service.py` (HTTP :8000) | `rest/inventory_service.py` (HTTP :8001) | `POST /inventory/check`, JSON | `requests` timeout = **2s** |
| **gRPC** | `grpc_version/order_service.py` (HTTP :8002) | `grpc_version/inventory_server.py` (gRPC :50051) | `InventoryService.CheckInventory` (`inventory.proto`) | gRPC deadline = **2s** |

Both Order Services expose the same client-facing API (`POST /orders`, `GET /health`) so they can be exercised with identical `curl` commands. Only the Order → Inventory hop changes between REST and gRPC.

Inventory stock (in memory, `common/inventory_data.py`): `apple: 10`, `banana: 5`, `laptop: 2`.

## Project layout

```
common/inventory_data.py        shared stock table
rest/inventory_service.py       REST Inventory Service (Flask)
rest/order_service.py           Order Service -> Inventory over REST/JSON
grpc_version/inventory.proto    gRPC service contract
grpc_version/inventory_pb2*.py  generated code (from inventory.proto)
grpc_version/inventory_server.py gRPC Inventory Service
grpc_version/order_service.py   Order Service -> Inventory over gRPC
grpc_version/client.py          direct gRPC client for the Inventory Service
scripts/demo.sh                 runs every scenario below end to end
evidence/                       captured output + service logs from demo.sh
```

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# (Optional) regenerate the gRPC stubs from the contract
python -m grpc_tools.protoc -I grpc_version --python_out=grpc_version \
    --grpc_python_out=grpc_version grpc_version/inventory.proto
```

## API contract

### REST – Inventory Service

`POST /inventory/check` with body `{"item_id": "<string>", "quantity": <int>}`

| Status | Meaning |
|---|---|
| `200 OK` | item exists and enough stock |
| `400 Bad Request` | malformed JSON / missing item_id / quantity ≤ 0 |
| `404 Not Found` | unknown `item_id` |
| `409 Conflict` | item exists but not enough stock |

The REST Order Service (`POST /orders`) returns `201 Created` on success, passes `400/404/409` through, returns **`504 Gateway Timeout`** when the Inventory call exceeds its 2s timeout, and `503` when Inventory is unreachable.

### gRPC – Inventory Service (`grpc_version/inventory.proto`)

```proto
service InventoryService {
  rpc CheckInventory(CheckInventoryRequest) returns (CheckInventoryResponse);
}
message CheckInventoryRequest  { string item_id = 1; int32 quantity = 2; }
message CheckInventoryResponse { string item_id = 1; int32 requested = 2; int32 in_stock = 3; bool available = 4; }
```

| gRPC status | Meaning | Mapped by Order Service to |
|---|---|---|
| `OK` | available | `201` |
| `INVALID_ARGUMENT` | empty item_id / quantity ≤ 0 | `400` |
| `NOT_FOUND` | unknown `item_id` | `404` |
| `FAILED_PRECONDITION` | not enough stock (item unavailable) | `409` |
| `DEADLINE_EXCEEDED` | Inventory slower than the 2s deadline | `504` |
| `UNAVAILABLE` | Inventory not reachable | `503` |

## Running the REST version

Each service in its own terminal (with the venv activated):

```bash
# Terminal 1 – Inventory Service (REST) on :8001
python rest/inventory_service.py

# Terminal 2 – Order Service (REST) on :8000, 2s timeout to Inventory
python rest/order_service.py

# Terminal 3 – place an order
curl -X POST http://localhost:8000/orders \
  -H 'Content-Type: application/json' -d '{"item_id":"apple","quantity":3}'
```

To simulate a slow Inventory Service, restart Terminal 1 with a delay longer than the timeout:

```bash
INVENTORY_DELAY_SECONDS=5 python rest/inventory_service.py
```

## Running the gRPC version

```bash
# Terminal 1 – Inventory Service (gRPC) on :50051
python grpc_version/inventory_server.py

# Terminal 2 – Order Service on :8002, calls Inventory over gRPC with a 2s deadline
python grpc_version/order_service.py

# Terminal 3 – place an order through the Order Service
curl -X POST http://localhost:8002/orders \
  -H 'Content-Type: application/json' -d '{"item_id":"apple","quantity":3}'

# ...or call the gRPC Inventory Service directly
python grpc_version/client.py apple 3
```

To simulate a slow Inventory Service:

```bash
INVENTORY_DELAY_SECONDS=5 python grpc_version/inventory_server.py
```

### Configuration

| Env var | Default | Used by |
|---|---|---|
| `INVENTORY_DELAY_SECONDS` | `0` | both Inventory Services (artificial delay) |
| `INVENTORY_TIMEOUT_SECONDS` | `2` | REST Order Service |
| `INVENTORY_DEADLINE_SECONDS` | `2` | gRPC Order Service |
| `ORDER_PORT` / `INVENTORY_PORT` | see table above | all services |

### One-shot demo

`./scripts/demo.sh` starts all services, runs every scenario below (including the slow-Inventory failures), and stops them. Its full output is saved in [`evidence/demo_output.txt`](evidence/demo_output.txt) and the per-service logs in [`evidence/logs/`](evidence/logs/). All output below was copied from that run.

---

## Evidence

### 1. Successful REST request and response

Calling the Inventory Service directly:

```
$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8001/inventory/check \
    -H 'Content-Type: application/json' -d '{"item_id":"apple","quantity":3}'
{"available":true,"in_stock":10,"item_id":"apple","requested":3}

HTTP 200
```

Through the Order Service (Order → Inventory over REST):

```
$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8000/orders \
    -H 'Content-Type: application/json' -d '{"item_id":"apple","quantity":3}'
{"inventory":{"available":true,"in_stock":10,"item_id":"apple","requested":3},"item_id":"apple","quantity":3,"status":"CONFIRMED"}

HTTP 201
```

Error status codes for unavailable / unknown / invalid items:

```
$ curl ... -d '{"item_id":"laptop","quantity":5}'
{"inventory":{"available":false,"error":"insufficient stock","in_stock":2,"item_id":"laptop","requested":5},"status":"REJECTED"}
HTTP 409

$ curl ... -d '{"item_id":"unicorn","quantity":1}'
{"inventory":{"error":"item 'unicorn' not found"},"status":"REJECTED"}
HTTP 404

$ curl ... -d '{"item_id":"apple","quantity":0}'
{"inventory":{"error":"quantity must be a positive integer"},"status":"REJECTED"}
HTTP 400
```

### 2. Successful gRPC request and response

Calling the gRPC Inventory Service directly:

```
$ python grpc_version/client.py apple 3
Request  -> CheckInventory({item_id: 'apple', quantity: 3}) deadline=2.0s
Response <- OK
item_id: "apple"
requested: 3
in_stock: 10
available: true
```

Through the Order Service (Order → Inventory over gRPC):

```
$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8002/orders \
    -H 'Content-Type: application/json' -d '{"item_id":"apple","quantity":3}'
{"inventory":{"available":true,"in_stock":10,"item_id":"apple","requested":3},"item_id":"apple","quantity":3,"status":"CONFIRMED"}

HTTP 201
```

gRPC error status when the item is unavailable (and the other error cases):

```
$ python grpc_version/client.py laptop 5
Request  -> CheckInventory({item_id: 'laptop', quantity: 5}) deadline=2.0s
Response <- FAILED_PRECONDITION: insufficient stock for 'laptop': requested 5, in stock 2

$ curl ... http://localhost:8002/orders -d '{"item_id":"laptop","quantity":5}'
{"error":"insufficient stock for 'laptop': requested 5, in stock 2","grpc_code":"FAILED_PRECONDITION","status":"REJECTED"}
HTTP 409

$ curl ... http://localhost:8002/orders -d '{"item_id":"unicorn","quantity":1}'
{"error":"item 'unicorn' not found","grpc_code":"NOT_FOUND","status":"REJECTED"}
HTTP 404

$ curl ... http://localhost:8002/orders -d '{"item_id":"apple","quantity":0}'
{"error":"quantity must be a positive integer","grpc_code":"INVALID_ARGUMENT","status":"REJECTED"}
HTTP 400
```

### 3. REST timeout handling

The REST Inventory Service was restarted with `INVENTORY_DELAY_SECONDS=5` (longer than the Order Service's 2s timeout):

```
$ curl -s -w '\nHTTP %{http_code}  (%{time_total}s)\n' -X POST http://localhost:8000/orders \
    -H 'Content-Type: application/json' -d '{"item_id":"apple","quantity":3}'
{"error":"inventory service timed out after 2.0s","status":"FAILED"}

HTTP 504  (2.004663s)
```

The client gets a clean `504 Gateway Timeout` after ~2s instead of waiting 5s. Logs:

```
# evidence/logs/rest_inventory_slow.log
REST Inventory Service on :8001 (delay=5.0s)
[2026-10-12 23:45:46,031] WARNING in inventory_service: Injecting artificial delay of 5.0s

# evidence/logs/rest_order.log
[2026-10-12 23:45:48,032] ERROR in order_service: Inventory check timed out after 2.0s
127.0.0.1 - - [12/Oct/2026 23:45:48] "POST /orders HTTP/1.1" 504 -
```

### 4. gRPC deadline handling

The gRPC Inventory Service was restarted with `INVENTORY_DELAY_SECONDS=5` (longer than the 2s deadline):

```
$ python grpc_version/client.py apple 3 2
Request  -> CheckInventory({item_id: 'apple', quantity: 3}) deadline=2.0s
Response <- DEADLINE_EXCEEDED: Deadline Exceeded

$ curl -s -w '\nHTTP %{http_code}  (%{time_total}s)\n' -X POST http://localhost:8002/orders \
    -H 'Content-Type: application/json' -d '{"item_id":"apple","quantity":3}'
{"error":"Deadline Exceeded","grpc_code":"DEADLINE_EXCEEDED","status":"FAILED"}

HTTP 504  (2.007985s)
```

Logs:

```
# evidence/logs/grpc_inventory_slow.log
gRPC Inventory Service on :50051 (delay=5.0s)
2026-10-12 23:45:48,656 WARNING inventory-grpc: Injecting artificial delay of 5.0s
2026-10-12 23:45:50,701 WARNING inventory-grpc: Injecting artificial delay of 5.0s

# evidence/logs/grpc_order.log
[2026-10-12 23:45:52,706] ERROR in order_service: Inventory RPC failed: DEADLINE_EXCEEDED - Deadline Exceeded
127.0.0.1 - - [12/Oct/2026 23:45:52] "POST /orders HTTP/1.1" 504 -
```

### 5. Order Service remains running after the failures

Immediately after each failure the **same Order Service process (same PID)** still answers health checks, and once the Inventory delay is removed it confirms new orders without being restarted.

**REST** (Order Service PID 87963):

```
$ ps -p 87963 -o pid=,command=
87963 .venv/bin/python rest/order_service.py

$ curl -s -w '\nHTTP %{http_code}\n' http://localhost:8000/health
{"service":"order-service-rest","status":"ok"}
HTTP 200

# Inventory restarted without the delay; Order Service untouched
$ curl ... http://localhost:8000/orders -d '{"item_id":"banana","quantity":1}'
{"inventory":{"available":true,"in_stock":5,"item_id":"banana","requested":1},"item_id":"banana","quantity":1,"status":"CONFIRMED"}
HTTP 201

$ ps -p 87963 -o pid=,command=
87963 .venv/bin/python rest/order_service.py
```

**gRPC** (Order Service PID 87999):

```
$ ps -p 87999 -o pid=,command=
87999 .venv/bin/python grpc_version/order_service.py

$ curl -s -w '\nHTTP %{http_code}\n' http://localhost:8002/health
{"service":"order-service-grpc","status":"ok"}
HTTP 200

# Inventory restarted without the delay; Order Service untouched
$ curl ... http://localhost:8002/orders -d '{"item_id":"banana","quantity":1}'
{"inventory":{"available":true,"in_stock":5,"item_id":"banana","requested":1},"item_id":"banana","quantity":1,"status":"CONFIRMED"}
HTTP 201

$ ps -p 87999 -o pid=,command=
87999 .venv/bin/python grpc_version/order_service.py
```

The full Order Service logs show the sequence `201 → 409 → 404 → 400 → 504 (timeout/deadline) → health 200 → 201` within one process: [`rest_order.log`](evidence/logs/rest_order.log), [`grpc_order.log`](evidence/logs/grpc_order.log).

<img width="715" height="186" alt="Screenshot 2026-10-12 at 11 59 56 PM" src="https://github.com/user-attachments/assets/1c07e312-dcef-4574-bd2a-12f5c8ee92c3" />
<img width="724" height="534" alt="Screenshot 2026-10-13 at 12 01 41 AM" src="https://github.com/user-attachments/assets/ac15b7da-3406-4602-837b-0b7677eebc43" />


---

## REST vs. gRPC comparison

With REST, the contract existed only implicitly in code and this README. I had to hand-validate JSON types (for example, rejecting a string `quantity`) and pick HTTP status codes such as 404 and 409 for each case. With gRPC, the `.proto` file was the single source of truth: the generated stubs gave typed request and response classes, so field names and types could not drift between client and server. Errors also felt more structured in gRPC because the server simply aborts with a canonical status such as `NOT_FOUND` or `FAILED_PRECONDITION`, whereas in REST the error details travel in a JSON body that each client must know how to parse. For failure handling, both produced a clean 2-second cutoff, but the REST `timeout` is a client-side socket setting, while the gRPC deadline is part of the call itself: it is propagated to the server in the `grpc-timeout` header, and the client gets a standard `DEADLINE_EXCEEDED` status. On the other hand, REST was easier to test and debug: `curl` works out of the box and the payloads are human-readable, while gRPC required a code-generation step, a dedicated client script, and binary Protobuf messages over HTTP/2.
