import pytest

from app.api.members import accept_pending_membership
from app.auth import AuthenticatedUser


class FakeQuery:
    def __init__(self, table, database):
        self.table = table
        self.database = database
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, *_args):
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def maybe_single(self):
        return self

    def execute(self):
        rows = [
            row for row in self.database.rows[self.table]
            if all(row.get(field) == value for field, value in self.filters)
        ]
        if self.operation == "update":
            for row in rows:
                row.update(self.payload)
        return type("Result", (), {"data": rows[0] if self.operation == "select" and len(rows) == 1 else rows})()


class FakeDatabase:
    def __init__(self):
        self.rows = {
            "workspace_members": [{
                "workspace_id": "workspace-a",
                "user_id": "user-1",
                "role": "agent",
                "status": "invited",
                "broker_id": None,
            }],
            "workspace_invitations": [{
                "workspace_id": "workspace-a",
                "email": "invite@example.com",
                "accepted_at": None,
            }],
        }

    def table(self, name):
        return FakeQuery(name, self)


@pytest.mark.asyncio
async def test_invited_user_activates_only_their_pending_membership():
    database = FakeDatabase()

    member = await accept_pending_membership(
        database,
        AuthenticatedUser(user_id="user-1", email="invite@example.com"),
        "workspace-a",
    )

    assert member["status"] == "active"
    assert database.rows["workspace_members"][0]["status"] == "active"
    assert database.rows["workspace_invitations"][0]["accepted_at"] is not None
