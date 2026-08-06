"""Input device seam: protocol + production adapter around pydirectinput.

Satu-satunya modul yang mengimpor ``pydirectinput``. Lapisan aksi
(``input_control``, ``safety``) menerima device lewat dependency injection
(default = adapter produksi), sehingga tes dapat menyuntikkan recorder
in-memory dan meng-assert urutan input tanpa men-patch namespace library.

Modul ini bebas-cycle: hanya bergantung pada stdlib dan ``pydirectinput``.
"""

from __future__ import annotations

from typing import Protocol

import pydirectinput

# PyDirectInput's failsafe is an emergency mechanism, not an anti-cheat feature.
pydirectinput.FAILSAFE = True
pydirectinput.PAUSE = 0.03


class DeviceInput(Protocol):
    """Minimal physical-input surface the action layer needs."""

    def position(self) -> tuple[int, int]: ...
    def moveTo(self, x: int, y: int) -> None: ...
    def keyDown(self, key: str) -> None: ...
    def keyUp(self, key: str) -> None: ...
    def click(self) -> None: ...
    def rightClick(self) -> None: ...


class PyDirectInputDevice:
    """Production adapter — wraps pydirectinput 1:1.

    Stateless: binding ``pydirectinput`` happens at module import, so a
    default instance may be bound once at function-definition time.
    """

    def position(self) -> tuple[int, int]:
        return pydirectinput.position()

    def moveTo(self, x: int, y: int) -> None:
        pydirectinput.moveTo(x, y)

    def keyDown(self, key: str) -> None:
        pydirectinput.keyDown(key)

    def keyUp(self, key: str) -> None:
        pydirectinput.keyUp(key)

    def click(self) -> None:
        pydirectinput.click()

    def rightClick(self) -> None:
        pydirectinput.rightClick()
