"""Fixtures shared by integration suites that run the real IPC protocol (from test_alpha2)."""

from tests.integration.test_alpha2 import api, env  # noqa: F401  (pytest fixtures)
from tests.regression.r5_harness import r5  # noqa: F401  (in-process world with a recording provider)
