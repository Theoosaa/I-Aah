"""Smoke test: the package is installed and importable."""

import iaah


def test_version_is_exposed() -> None:
    assert iaah.__version__.count(".") == 2
