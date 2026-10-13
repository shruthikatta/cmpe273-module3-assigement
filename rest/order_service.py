"""Order Service that talks to the Inventory Service over REST/HTTP + JSON.

POST /orders  {"item_id": str, "quantity": int}
GET  /health
"""
import os

import requests
from flask import Flask, jsonify, request

PORT = int(os.environ.get("ORDER_PORT", "8000"))
INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://localhost:8001")
TIMEOUT_SECONDS = float(os.environ.get("INVENTORY_TIMEOUT_SECONDS", "2"))

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok", service="order-service-rest"), 200


@app.post("/orders")
def create_order():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400

    payload = {"item_id": body.get("item_id"), "quantity": body.get("quantity")}

    try:
        resp = requests.post(
            f"{INVENTORY_URL}/inventory/check",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        app.logger.error("Inventory check timed out after %.1fs", TIMEOUT_SECONDS)
        return jsonify(
            status="FAILED",
            error=f"inventory service timed out after {TIMEOUT_SECONDS}s",
        ), 504
    except requests.exceptions.ConnectionError:
        app.logger.error("Inventory service unreachable at %s", INVENTORY_URL)
        return jsonify(status="FAILED", error="inventory service unavailable"), 503

    inventory = resp.json()

    if resp.status_code == 200:
        return jsonify(
            status="CONFIRMED",
            item_id=inventory["item_id"],
            quantity=inventory["requested"],
            inventory=inventory,
        ), 201

    if resp.status_code in (400, 404, 409):
        return jsonify(status="REJECTED", inventory=inventory), resp.status_code

    return jsonify(status="FAILED", error="unexpected inventory response", inventory=inventory), 502


if __name__ == "__main__":
    print(f"REST Order Service on :{PORT} -> {INVENTORY_URL} (timeout={TIMEOUT_SECONDS}s)", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
