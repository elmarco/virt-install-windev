from __future__ import annotations

import pytest

from virt_install_windev.config import Config, WinVersion


@pytest.fixture(params=[WinVersion.WIN11, WinVersion.WIN10,
                        WinVersion.SERVER2016, WinVersion.SERVER2022])
def config(request) -> Config:
    return Config(win_version=request.param)
