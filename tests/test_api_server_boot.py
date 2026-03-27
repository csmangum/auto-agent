"""Smoke tests: FastAPI app boots and route table has no duplicate handlers."""

from collections import Counter

from fastapi.routing import APIRoute
from starlette.routing import Mount


def _iter_route_method_paths(routes, prefix: str = "") -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for route in routes:
        if isinstance(route, Mount):
            mount_path = str(route.path).rstrip("/")
            sub_prefix = prefix.rstrip("/") + "/" + mount_path.lstrip("/")
            if not sub_prefix.endswith("/"):
                sub_prefix += "/"
            pairs.extend(_iter_route_method_paths(route.routes, sub_prefix))
        elif isinstance(route, APIRoute):
            path = prefix.rstrip("/") + route.path
            path = path.replace("//", "/")
            for method in route.methods:
                if method == "HEAD":
                    continue
                pairs.append((method, path))
    return pairs


def test_server_app_imports() -> None:
    """Regression: route modules must import cleanly (no NameError at load time)."""
    from claim_agent.api.server import app  # noqa: PLC0415

    assert app is not None
    assert app.title


def test_no_duplicate_http_routes() -> None:
    """Each (method, path) should map to exactly one route (no shadowed duplicates)."""
    from claim_agent.api.server import app  # noqa: PLC0415

    pairs = _iter_route_method_paths(app.routes)
    counts = Counter(pairs)
    dupes = {k: v for k, v in counts.items() if v > 1}
    assert not dupes, f"Duplicate route registrations: {dupes}"
