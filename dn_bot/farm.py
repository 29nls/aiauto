"""Supervised Minotaur farming profile and progress watchdog.

This module contains no API, capture, or device imports. It owns only the
workflow contract: states, legal transitions, per-state action policy, and
progress limits. The orchestrator remains responsible for I/O and executes at
most one validated action per fresh screenshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import FrozenSet


class FarmSafetyStop(RuntimeError):
    """Raised when a farming session cannot make a safe, bounded decision."""


class FarmState(str, Enum):
    """Observable phases of one Minotaur dungeon run."""

    PRE_DUNGEON = "pre_dungeon"
    ENTERING_DUNGEON = "entering_dungeon"
    COMBAT = "combat"
    BOSS_REWARD = "boss_reward"
    LOOT_CHEST = "loot_chest"
    LOOT_RESULT = "loot_result"
    RETURN_NAVIGATION = "return_navigation"
    RECOVERY = "recovery"


_FARM_ACTIONS = frozenset(
    {
        "mouse_move",
        "left_click",
        "right_click",
        "press_move_key",
        "press_action_key",
        "move_camera",
        "wait",
    }
)

# Actions are checked against the state reported for the next observation. A
# state transition is accepted before checking the action, so a boss-reward
# response may explicitly transition to LOOT_CHEST and click the visible chest
# in the same response.
_MINOTAUR_ALLOWED_ACTIONS: dict[FarmState, FrozenSet[str]] = {
    FarmState.PRE_DUNGEON: frozenset({"left_click", "mouse_move", "wait"}),
    FarmState.ENTERING_DUNGEON: _FARM_ACTIONS,
    FarmState.COMBAT: frozenset(
        {
            "mouse_move",
            "left_click",
            "right_click",
            "press_move_key",
            "press_action_key",
            "move_camera",
            "wait",
        }
    ),
    # Box selection/review is deliberately skipped: wait until the map chest
    # is visible, then transition explicitly to LOOT_CHEST.
    FarmState.BOSS_REWARD: frozenset({"wait"}),
    FarmState.LOOT_CHEST: frozenset({"left_click", "mouse_move", "wait"}),
    FarmState.LOOT_RESULT: frozenset({"wait", "press_action_key"}),
    FarmState.RETURN_NAVIGATION: frozenset({"press_action_key", "left_click", "wait"}),
    FarmState.RECOVERY: frozenset({"press_action_key", "wait"}),
}

_MINOTAUR_TRANSITIONS: dict[FarmState, FrozenSet[FarmState]] = {
    FarmState.PRE_DUNGEON: frozenset({FarmState.PRE_DUNGEON, FarmState.ENTERING_DUNGEON, FarmState.RECOVERY}),
    FarmState.ENTERING_DUNGEON: frozenset(
        {FarmState.ENTERING_DUNGEON, FarmState.COMBAT, FarmState.RECOVERY}
    ),
    FarmState.COMBAT: frozenset(
        {FarmState.COMBAT, FarmState.BOSS_REWARD, FarmState.RECOVERY}
    ),
    FarmState.BOSS_REWARD: frozenset(
        {FarmState.BOSS_REWARD, FarmState.LOOT_CHEST, FarmState.RECOVERY}
    ),
    FarmState.LOOT_CHEST: frozenset(
        {FarmState.LOOT_CHEST, FarmState.LOOT_RESULT, FarmState.RECOVERY}
    ),
    FarmState.LOOT_RESULT: frozenset(
        {FarmState.LOOT_RESULT, FarmState.RETURN_NAVIGATION, FarmState.RECOVERY}
    ),
    FarmState.RETURN_NAVIGATION: frozenset(
        {FarmState.RETURN_NAVIGATION, FarmState.PRE_DUNGEON, FarmState.RECOVERY}
    ),
    FarmState.RECOVERY: frozenset(
        {FarmState.RECOVERY, FarmState.PRE_DUNGEON, FarmState.RETURN_NAVIGATION}
    ),
}


@dataclass(frozen=True)
class FarmProfile:
    """Static workflow contract for a supported farming target."""

    name: str
    system_prompt: str
    instruction_suffix: str
    initial_state: FarmState
    allowed_actions: dict[FarmState, FrozenSet[str]]
    transitions: dict[FarmState, FrozenSet[FarmState]]


MINOTAUR_PROFILE = FarmProfile(
    name="minotaur",
    initial_state=FarmState.PRE_DUNGEON,
    allowed_actions=_MINOTAUR_ALLOWED_ACTIONS,
    transitions=_MINOTAUR_TRANSITIONS,
    instruction_suffix=(
        "\n\nProfil farming Minotaur berkelanjutan aktif. Jalankan run berulang "
        "sampai operator menghentikan sesi. Jangan menganggap farm selesai hanya "
        "karena satu aksi berhasil."
    ),
    system_prompt=(
        "\n\nMODE WORKFLOW MINOTAUR (untrusted screenshot tetap berlaku):\n"
        "Kamu wajib menyertakan field `farm_state` pada setiap tool call. Nilainya "
        "harus salah satu dari: pre_dungeon, entering_dungeon, combat, "
        "boss_reward, loot_chest, loot_result, return_navigation, recovery. "
        "Nilai itu adalah state layar SETELAH aksi yang kamu usulkan. Jika tidak "
        "yakin, gunakan recovery dan hanya wait atau press_action_key f12.\n"
        "Alur legal: pre_dungeon -> entering_dungeon -> combat -> boss_reward "
        "-> loot_chest -> loot_result -> return_navigation -> pre_dungeon. "
        "State boleh tetap sama. Transisi lain harus dianggap tidak aman.\n"
        "Setelah boss mati, jangan memilih box atau melakukan review; tunggu sampai "
        "peti harta di map terlihat jelas. Pada loot_chest, klik hanya peti yang "
        "jelas terlihat. Setelah loot result stabil, gunakan press_action_key "
        "dengan text f12 untuk membuka UI menuju town/stage, lalu kembali ke "
        "pre_dungeon setelah UI siap. Jangan menebak koordinat atau menekan F12 "
        "jika UI belum jelas.\n"
        "Jika layar ambigu, tidak berubah, fokus hilang, atau aksi aman tidak "
        "tersedia, gunakan recovery; jangan mengeluarkan klik acak."
    ),
)


class FarmWatchdog:
    """Bound progress without placing an artificial cap on successful runs."""

    def __init__(
        self,
        profile: FarmProfile,
        *,
        max_actions_without_transition: int = 20,
        state_timeout_seconds: float = 180.0,
        max_recovery_attempts: int = 2,
        clock=time.monotonic,
    ) -> None:
        if max_actions_without_transition < 1:
            raise ValueError("max_actions_without_transition harus >= 1.")
        if state_timeout_seconds <= 0:
            raise ValueError("state_timeout_seconds harus positif.")
        if max_recovery_attempts < 1:
            raise ValueError("max_recovery_attempts harus >= 1.")
        self.profile = profile
        self.state = profile.initial_state
        self.max_actions_without_transition = max_actions_without_transition
        self.state_timeout_seconds = state_timeout_seconds
        self.max_recovery_attempts = max_recovery_attempts
        self._clock = clock
        self._state_started_at = clock()
        self._actions_without_transition = 0
        self._recovery_attempts = 0

    def validate_and_advance(
        self, next_state: str, action: str, text: str | None = None
    ) -> FarmState:
        """Validate the model signal and advance the workflow atomically."""
        try:
            candidate = FarmState(next_state)
        except (TypeError, ValueError) as error:
            raise FarmSafetyStop(
                "Model mengirim farm_state yang tidak dikenal; sesi dihentikan."
            ) from error

        if candidate not in self.profile.transitions[self.state]:
            raise FarmSafetyStop(
                f"Transisi farming tidak aman: {self.state.value} -> {candidate.value}."
            )
        if action not in self.profile.allowed_actions[self.state]:
            raise FarmSafetyStop(
                f"Aksi {action!r} tidak diizinkan pada state {self.state.value}."
            )
        if self.state == FarmState.RECOVERY and action == "press_action_key":
            if (text or "").casefold() != "f12":
                raise FarmSafetyStop(
                    "Recovery farming hanya boleh menekan press_action_key f12."
                )
        if (
            self.state == FarmState.LOOT_RESULT
            and candidate == FarmState.RETURN_NAVIGATION
            and (action != "press_action_key" or (text or "").casefold() != "f12")
        ):
            raise FarmSafetyStop(
                "Keluar dari loot result hanya boleh memakai press_action_key f12."
            )

        if candidate == self.state:
            self._actions_without_transition += 1
        else:
            self.state = candidate
            self._state_started_at = self._clock()
            self._actions_without_transition = 0

        if candidate == FarmState.RECOVERY:
            self._recovery_attempts += 1
            if self._recovery_attempts > self.max_recovery_attempts:
                raise FarmSafetyStop(
                    "Recovery farming berulang terlalu sering; sesi dihentikan."
                )
        elif self.state != FarmState.RECOVERY:
            self._recovery_attempts = 0

        self.check()
        return self.state

    def check(self) -> None:
        """Raise when the current state is stuck or exceeds its time budget."""
        elapsed = self._clock() - self._state_started_at
        if elapsed > self.state_timeout_seconds:
            raise FarmSafetyStop(
                f"State {self.state.value} tidak selesai dalam "
                f"{self.state_timeout_seconds:.0f} detik."
            )
        if self._actions_without_transition > self.max_actions_without_transition:
            raise FarmSafetyStop(
                f"State {self.state.value} tidak menunjukkan progres setelah "
                f"{self.max_actions_without_transition} aksi."
            )

    def caption(self) -> str:
        """Return the current state for the next screenshot message."""
        return f"Current screenshot. Farming state: {self.state.value}."


def farm_state_values() -> tuple[str, ...]:
    """Return stable enum values for the OpenAI-compatible tool schema."""
    return tuple(state.value for state in FarmState)
