"""Order Service that talks to the Inventory Service over gRPC.

The Order Service itself still exposes a small HTTP API so it can be driven
with curl exactly like the REST version; only the Order -> Inventory hop
uses gRPC.

POST /orders  {"item_id": str, "quantity": int}
GET  /health
"""
import os
import sys

import grpc
from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(__file__))

import inventory_pb2  # noqa: E402
import inventory_pb2_grpc  # noqa: E402

PORT = int(os.environ.get("ORDER_PORT", "8002"))
INVENTORY_ADDR = os.environ.get("INVENTORY_ADDR", "localhost:50051")
DEADLINE_SECONDS = float(os.environ.get("INVENTORY_DEADLINE_SECONDS", "2"))

GRPC_TO_HTTP = {
    grpc.StatusCode.INVALID_ARGUMENT: 400,
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.FAILED_PRECONDITION: 409,
    grpc.StatusCode.DEADLINE_EXCEEDED: 504,
    grpc.StatusCode.UNAVAILABLE: 503,
}

app = Flask(__name__)
channel = grpc.insecure_channel(INVENTORY_ADDR)
stub = inventory_pb2_grpc.InventoryServiceStub(channel)


@app.get("/health")
def health():
    return jsonify(status="ok", service="order-service-grpc"), 200


@app.post("/orders")
def create_order():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400

    item_id = body.get("item_id")
    quantity = body.get("quantity")
    if not isinstance(item_id, str) or not isinstance(quantity, int) or isinstance(quantity, bool):
        return jsonify(error="item_id must be a string and quantity an integer"), 400

    try:
        resp = stub.CheckInventory(
            inventory_pb2.CheckInventoryRequest(item_id=item_id, quantity=quantity),
            timeout=DEADLINE_SECONDS,
        )
    except grpc.RpcError as err:
        code = err.code()
        app.logger.error("Inventory RPC failed: %s - %s", code.name, err.details())
        http_status = GRPC_TO_HTTP.get(code, 502)
        status = "REJECTED" if http_status in (400, 404, 409) else "FAILED"
        return jsonify(status=status, grpc_code=code.name, error=err.details()), http_status

    return jsonify(
        status="CONFIRMED",
        item_id=resp.item_id,
        quantity=resp.requested,
        inventory={
            "item_id": resp.item_id,
            "requested": resp.requested,
            "in_stock": resp.in_stock,
            "available": resp.available,
        },
    ), 201


if __name__ == "__main__":
    print(f"gRPC Order Service on :{PORT} -> {INVENTORY_ADDR} (deadline={DEADLINE_SECONDS}s)", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
