"""RBAC role names shared across API, DB, and config (avoid api → db import cycles)."""

KNOWN_ROLES = frozenset({"adjuster", "supervisor", "admin", "executive", "shop_user"})
