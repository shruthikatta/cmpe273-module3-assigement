"""Direct gRPC client for the Inventory Service (bypasses the Order Service).

Usage: python grpc_version/client.py <item_id> <quantity> [deadline_seconds]
"""
import os
import sys

import grpc

sys.path.insert(0, os.path.dirname(__file__))

import inventory_pb2  # noqa: E402
import inventory_pb2_grpc  # noqa: E402


def main():
    item_id = sys.argv[1] if len(sys.argv) > 1 else "apple"
    quantity = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    deadline = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    addr = os.environ.get("INVENTORY_ADDR", "localhost:50051")

    with grpc.insecure_channel(addr) as channel:
        stub = inventory_pb2_grpc.InventoryServiceStub(channel)
        req = inventory_pb2.CheckInventoryRequest(item_id=item_id, quantity=quantity)
        print(f"Request  -> CheckInventory({{item_id: {item_id!r}, quantity: {quantity}}}) deadline={deadline}s")
        try:
            resp = stub.CheckInventory(req, timeout=deadline)
            print("Response <- OK")
            print(resp, end="")
        except grpc.RpcError as err:
            print(f"Response <- {err.code().name}: {err.details()}")
            sys.exit(1)


if __name__ == "__main__":
    main()
