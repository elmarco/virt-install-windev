from __future__ import annotations

import pytest


@pytest.fixture(params=["win11", "win10", "server2016", "server2022"])
def config_version(request) -> str:
    return request.param
