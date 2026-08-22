"""Auth context — mocked identity/role, real enforcement.

The context is created by the application (from a login/session), NEVER by the
model. Every scoped tool takes a context and enforces it in code, so a prompt-
injection telling the agent to "read ACCT-001" cannot widen access.
"""
from __future__ import annotations

from dataclasses import dataclass


class AccessDenied(Exception):
    """Raised when a context requests data outside its scope."""


@dataclass(frozen=True)
class AuthContext:
    role: str                    # "customer" | "internal"
    account_id: str | None = None  # required for customer; ignored for internal

    @property
    def is_internal(self) -> bool:
        return self.role == "internal"

    def assert_can_read_account(self, account_id: str) -> None:
        """Customers may only read their own account. Internal staff read any."""
        if self.is_internal:
            return
        if self.account_id is None or account_id != self.account_id:
            raise AccessDenied(
                f"role={self.role} scope={self.account_id} cannot access {account_id}"
            )


# convenience constructors for demos / tests
def customer(account_id: str) -> AuthContext:
    return AuthContext(role="customer", account_id=account_id)


def internal() -> AuthContext:
    return AuthContext(role="internal")
