"""Top-level conftest for pytest."""

# Do NOT add pytest_plugins = ["tests.integration.conftest"] here.
# That causes double registration: pytest auto-loads tests/integration/conftest.py
# when collecting tests in that directory, so explicit loading duplicates the plugin.
