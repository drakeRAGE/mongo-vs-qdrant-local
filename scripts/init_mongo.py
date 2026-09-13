"""Initiate rs0 and create mongotUser after mongod is listening."""

from __future__ import annotations

import time

from pymongo import MongoClient
from pymongo.errors import OperationFailure


def main() -> int:
    client = MongoClient("mongodb://127.0.0.1:27018/?directConnection=true", serverSelectionTimeoutMS=8000)
    for _ in range(40):
        try:
            client.admin.command("ping")
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("mongod did not accept ping")

    try:
        status = client.admin.command("replSetGetStatus")
        print("replica set already initiated:", status.get("set"))
    except OperationFailure:
        client.admin.command(
            {
                "replSetInitiate": {
                    "_id": "rs0",
                    "members": [{"_id": 0, "host": "mongod:27017"}],
                }
            }
        )
        print("initiated rs0 with member mongod:27017")
        time.sleep(2)

    admin = client["admin"]
    try:
        admin.command(
            "createUser",
            "mongotUser",
            pwd="mongotPassword",
            roles=[{"role": "searchCoordinator", "db": "admin"}],
        )
        print("created mongotUser")
    except OperationFailure as exc:
        if exc.code == 51003 or "already exists" in str(exc).lower() or exc.code == 51003:
            print("mongotUser already exists")
        else:
            # 51003 = Location51003 user exists in some builds; 11000 duplicate
            print("createUser:", exc)
    try:
        admin.command(
            "createUser",
            "admin",
            pwd="admin",
            roles=[{"role": "root", "db": "admin"}],
        )
        print("created admin")
    except OperationFailure:
        print("admin user exists or auth not enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
