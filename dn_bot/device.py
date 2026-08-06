"""Input device seam: protocol + production adapter around pydirectinput.

Satu-satunya modul yang mengimpor ``pydirectinput``. Lapisan aksi
(``input_control``, ``safety``) menerima device lewat dependency injection
(default = adapter produksi), sehingga tes dapat menyuntikkan recorder
in-memory dan meng-assert urutan input tanpa men-patch namespace library.

Selain adapter produksi, modul ini menyediakan ``DryRunDevice`` — implementasi
kedua protocol yang meng-log aksi fisik yang dimaksud tanpa mengeksekusinya
(mode ``--dry-run``). Modul ini bebas-cycle: hanya bergantung pada stdlib,
``pydirectinput``, dan ``config`` (untuk ``log``).
"""

from __future__ import annotations

from typing import Protocol

import pydirectinput

from .config import log

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


class DryRunDevice:
    """Rehearsal device: logs intended physical actions, performs none.

    Implements the ``DeviceInput`` surface. Every physical primitive is logged
    (``[dry-run] ...``) instead of executed, so an operator can rehearse the
    full capture -> model -> action -> next-frame loop with zero physical
    input (flag ``--dry-run``). Each call is also recorded in ``calls`` so
    tests can assert the intended input sequence without touching the
    production adapter.

    ``position()`` returns a fixed safe coordinate — never the failsafe
    corner — because the bot never moves the cursor in dry-run: the corner
    emergency stop is a physical-input mechanism that is moot when no input
    can occur. ``Ctrl+C`` (or the window-focus guard) remains the abort.
    Position reads are recorded in ``calls`` but deliberately NOT logged
    (they are observations, and would flood the log during sleep ticks).
    """

    # Default cursor position used by ``position()``; (100, 100) is safely
    # outside the failsafe corner (0-5 px), so real emergency-stop checks
    # pass trivially during a rehearsal.
    SAFE_POSITION = (100, 100)

    def __init__(self, position: tuple[int, int] = SAFE_POSITION) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._position = tuple(position)

    def position(self) -> tuple[int, int]:
        self.calls.append(("position", ()))
        return self._position

    def moveTo(self, x: int, y: int) -> None:
        self.calls.append(("moveTo", (x, y)))
        log.info("[dry-run] moveTo(%d, %d)", x, y)

    def keyDown(self, key: str) -> None:
        self.calls.append(("keyDown", (key,)))
        log.info("[dry-run] keyDown(%s)", key)

    def keyUp(self, key: str) -> None:
        self.calls.append(("keyUp", (key,)))
        log.info("[dry-run] keyUp(%s)", key)

    def click(self) -> None:
        self.calls.append(("click", ()))
        log.info("[dry-run] click()")

    def rightClick(self) -> None:
        self.calls.append(("rightClick", ()))
        log.info("[dry-run] rightClick()")
