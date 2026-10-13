"""REST Inventory Service.

POST /inventory/check  {"item_id": str, "quantity": int}

  200 OK        item exists and enough stock is available
  400 Bad Req.  malformed body / invalid quantity
  404 Not Found unknown item_id
  409 Conflict  item exists but not enough stock

Set INVENTORY_DELAY_SECONDS to inject an artificial delay (failure demo).
"""
import os
import sys
import time

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.inventory_data import STOCK  # noqa: E402

PORT = int(os.environ.get("INVENTORY_PORT", "8001"))
DELAY_SECONDS = float(os.environ.get("INVENTORY_DELAY_SECONDS", "0"))

app = Flask(__name__)


@app.post("/inventory/check")
def check_inventory():
    if DELAY_SECONDS > 0:
        app.logger.warning("Injecting artificial delay of %.1fs", DELAY_SECONDS)
        time.sleep(DELAY_SECONDS)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400

    item_id = body.get("item_id")
    quantity = body.get("quantity")
    if not isinstance(item_id, str) or not item_id:
        return jsonify(error="item_id must be a non-empty string"), 400
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return jsonify(error="quantity must be a positive integer"), 400

    if item_id not in STOCK:
        return jsonify(error=f"item '{item_id}' not found"), 404

    in_stock = STOCK[item_id]
    if quantity > in_stock:
        return jsonify(
            item_id=item_id,
            requested=quantity,
            in_stock=in_stock,
            available=False,
            error="insufficient stock",
        ), 409

    return jsonify(item_id=item_id, requested=quantity, in_stock=in_stock, available=True), 200


if __name__ == "__main__":
    print(f"REST Inventory Service on :{PORT} (delay={DELAY_SECONDS}s)", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
