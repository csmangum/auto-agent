"""Top-level conftest for pytest.

pytest_plugins must be defined here (not in subdir conftests) per pytest deprecation.
"""

pytest_plugins = ["tests.integration.conftest"]  # noqa: F401
