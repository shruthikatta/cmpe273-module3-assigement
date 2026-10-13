"""gRPC Inventory Service.

Set INVENTORY_DELAY_SECONDS to inject an artificial delay (failure demo).
"""
import logging
import os
import sys
import time
from concurrent import futures

import grpc

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import inventory_pb2  # noqa: E402
import inventory_pb2_grpc  # noqa: E402
from common.inventory_data import STOCK  # noqa: E402

PORT = int(os.environ.get("INVENTORY_PORT", "50051"))
DELAY_SECONDS = float(os.environ.get("INVENTORY_DELAY_SECONDS", "0"))

log = logging.getLogger("inventory-grpc")


class InventoryService(inventory_pb2_grpc.InventoryServiceServicer):
    def CheckInventory(self, request, context):
        if DELAY_SECONDS > 0:
            log.warning("Injecting artificial delay of %.1fs", DELAY_SECONDS)
            time.sleep(DELAY_SECONDS)

        if not request.item_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "item_id must be non-empty")
        if request.quantity <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "quantity must be a positive integer")

        if request.item_id not in STOCK:
            context.abort(grpc.StatusCode.NOT_FOUND, f"item '{request.item_id}' not found")

        in_stock = STOCK[request.item_id]
        if request.quantity > in_stock:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"insufficient stock for '{request.item_id}': requested {request.quantity}, in stock {in_stock}",
            )

        return inventory_pb2.CheckInventoryResponse(
            item_id=request.item_id,
            requested=request.quantity,
            in_stock=in_stock,
            available=True,
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(InventoryService(), server)
    server.add_insecure_port(f"localhost:{PORT}")
    server.start()
    print(f"gRPC Inventory Service on :{PORT} (delay={DELAY_SECONDS}s)", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    serve()
