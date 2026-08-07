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

from .config import TARGET_HEIGHT, TARGET_WIDTH


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
    RETREAT_DIALOG = "retreat_dialog"
    RETURN_WAIT = "return_wait"
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

_MINOTAUR_ALLOWED_ACTIONS: dict[FarmState, FrozenSet[str]] = {
    FarmState.PRE_DUNGEON: frozenset({"left_click", "mouse_move", "wait"}),
    FarmState.ENTERING_DUNGEON: _FARM_ACTIONS,
    FarmState.COMBAT: _FARM_ACTIONS,
    # Box selection/review is deliberately skipped: wait until the map chest
    # is visible, then transition explicitly to LOOT_CHEST.
    FarmState.BOSS_REWARD: frozenset({"wait"}),
    FarmState.LOOT_CHEST: frozenset({"left_click", "mouse_move", "wait"}),
    # The exit prompt is visible while loot settles. F12 is the only action
    # that may leave the loot-result phase; the model must report the retreat
    # dialog that appears after the key press.
    FarmState.LOOT_RESULT: frozenset({"wait", "press_action_key"}),
    # The retreat dialog offers Stage Entrance/Town. Only a clearly recognized
    # click or a wait is safe here; pressing F12 again is never valid.
    FarmState.RETREAT_DIALOG: frozenset({"left_click", "wait"}),
    # Loading/transition after selecting the retreat destination is passive.
    FarmState.RETURN_WAIT: frozenset({"wait"}),
    FarmState.RECOVERY: frozenset({"press_action_key", "wait"}),
}

_MINOTAUR_TRANSITIONS: dict[FarmState, FrozenSet[FarmState]] = {
    FarmState.PRE_DUNGEON: frozenset(
        {FarmState.PRE_DUNGEON, FarmState.ENTERING_DUNGEON, FarmState.RECOVERY}
    ),
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
        {FarmState.LOOT_RESULT, FarmState.RETREAT_DIALOG, FarmState.RECOVERY}
    ),
    FarmState.RETREAT_DIALOG: frozenset(
        {FarmState.RETREAT_DIALOG, FarmState.RETURN_WAIT, FarmState.RECOVERY}
    ),
    FarmState.RETURN_WAIT: frozenset(
        {FarmState.RETURN_WAIT, FarmState.PRE_DUNGEON, FarmState.RECOVERY}
    ),
    FarmState.RECOVERY: frozenset(
        {FarmState.RECOVERY, FarmState.PRE_DUNGEON}
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
        "boss_reward, loot_chest, loot_result, retreat_dialog, return_wait, "
        "recovery. "
        "Nilai itu adalah state layar SETELAH aksi yang kamu usulkan. Jika tidak "
        "yakin, gunakan recovery dan hanya wait atau press_action_key f12.\n"
        "Alur legal: pre_dungeon -> entering_dungeon -> combat -> boss_reward "
        "-> loot_chest -> loot_result -> retreat_dialog -> return_wait "
        "-> pre_dungeon. "
        "State boleh tetap sama. Transisi lain harus dianggap tidak aman.\n"
        "Setelah boss mati, jangan memilih box atau melakukan review; tunggu sampai "
        "peti harta di map terlihat jelas. Pada loot_chest, klik hanya peti yang "
        "jelas terlihat. Setelah loot result stabil dan F12 terlihat, gunakan "
        "press_action_key dengan text f12 untuk membuka dialog Stage Entrance/Town "
        "dan laporkan retreat_dialog. Pada retreat_dialog, klik hanya opsi Town atau "
        "Stage Entrance yang terlihat jelas (atau wait); jangan menekan F12 lagi. "
        "Setelah memilih lokasi, laporkan return_wait dan hanya wait sampai layar "
        "pre_dungeon siap. Jangan menebak koordinat atau melompati dialog.\n"
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
        max_actions_per_run: int = 200,
        state_timeout_seconds: float = 180.0,
        max_recovery_attempts: int = 2,
        clock=time.monotonic,
    ) -> None:
        if max_actions_without_transition < 1:
            raise ValueError("max_actions_without_transition harus >= 1.")
        if max_actions_per_run < 1:
            raise ValueError("max_actions_per_run harus >= 1.")
        if state_timeout_seconds <= 0:
            raise ValueError("state_timeout_seconds harus positif.")
        if max_recovery_attempts < 1:
            raise ValueError("max_recovery_attempts harus >= 1.")
        self.profile = profile
        self.state = profile.initial_state
        self.max_actions_without_transition = max_actions_without_transition
        self.max_actions_per_run = max_actions_per_run
        self.state_timeout_seconds = state_timeout_seconds
        self.max_recovery_attempts = max_recovery_attempts
        self._clock = clock
        self._state_started_at = clock()
        self._actions_without_transition = 0
        self._actions_in_run = 0
        self._recovery_attempts = 0
        self._loot_result_stabilized = False
        self.completed_runs = 0

    def validate(
        self,
        next_state: str,
        action: str,
        text: str | None = None,
        coordinate: object | None = None,
    ) -> FarmState:
        """Validate a proposed transition without mutating workflow state."""
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
        if not isinstance(action, str):
            raise FarmSafetyStop(
                "Model mengirim action yang kosong atau bukan teks; sesi dihentikan."
            )
        if self.state == FarmState.RETREAT_DIALOG and action == "press_action_key":
            raise FarmSafetyStop(
                "Dialog retreat tidak boleh menekan F12; pilih Town atau Stage Entrance."
            )
        if action not in self.profile.allowed_actions[self.state]:
            raise FarmSafetyStop(
                f"Aksi {action!r} tidak diizinkan pada state {self.state.value}."
            )
        normalized_text = (
            " ".join(text.casefold().split()) if isinstance(text, str) else ""
        )
        if self.state == FarmState.RECOVERY:
            if action == "press_action_key" and normalized_text != "f12":
                raise FarmSafetyStop(
                    "Navigasi farming hanya boleh menekan press_action_key f12."
                )
            if candidate == FarmState.PRE_DUNGEON and action != "wait":
                raise FarmSafetyStop(
                    "Recovery hanya boleh melaporkan pre_dungeon setelah wait "
                    "berhasil dan layar baru terkonfirmasi."
                )
        if self.state == FarmState.LOOT_RESULT and candidate == FarmState.RETREAT_DIALOG:
            if action != "press_action_key" or normalized_text != "f12":
                raise FarmSafetyStop(
                    "Keluar dari loot result hanya boleh memakai press_action_key f12."
                )
            if not self._loot_result_stabilized:
                raise FarmSafetyStop(
                    "Loot belum stabil; lakukan wait di loot_result sebelum menekan F12."
                )
        if self.state == FarmState.RETREAT_DIALOG:
            if action == "wait" and candidate == FarmState.RETREAT_DIALOG:
                return candidate
            if action == "left_click" and candidate == FarmState.RETURN_WAIT:
                if _is_screen_coordinate(coordinate) and normalized_text in {
                    "town",
                    "stage entrance",
                }:
                    return candidate
                raise FarmSafetyStop(
                    "Dialog retreat hanya boleh klik opsi Town atau Stage Entrance "
                    "yang terlihat jelas."
                )
            raise FarmSafetyStop(
                "Dialog retreat hanya boleh wait atau klik Town/Stage Entrance."
            )
        return candidate

    def ensure_action_allowed(self, candidate: FarmState | None = None) -> None:
        """Reject the next physical action before it can be executed."""
        if self._actions_without_transition >= self.max_actions_without_transition:
            raise FarmSafetyStop(
                f"State {self.state.value} tidak menunjukkan progres setelah "
                f"{self.max_actions_without_transition} aksi."
            )
        if self._actions_in_run >= self.max_actions_per_run:
            raise FarmSafetyStop(
                f"Run melewati batas {self.max_actions_per_run} aksi; sesi dihentikan."
            )
        if (
            candidate == FarmState.RECOVERY
            and self.state != FarmState.RECOVERY
            and self._recovery_attempts >= self.max_recovery_attempts
        ):
            raise FarmSafetyStop(
                "Recovery farming berulang terlalu sering; sesi dihentikan."
            )

    def advance(self, candidate: FarmState, action: str) -> FarmState:
        """Commit a previously validated transition after its action succeeds."""
        self.ensure_action_allowed(candidate)
        previous = self.state
        if candidate == previous:
            self._actions_without_transition += 1
        else:
            self.state = candidate
            self._state_started_at = self._clock()
            self._actions_without_transition = 0

        self._actions_in_run += 1
        if candidate == FarmState.PRE_DUNGEON and previous == FarmState.RETURN_WAIT:
            self.completed_runs += 1
            self._actions_in_run = 0
        elif candidate == FarmState.PRE_DUNGEON and previous == FarmState.RECOVERY:
            # Recovery may abandon a broken run at the safe pre-dungeon screen;
            # do not carry the failed run's action budget into the next run.
            self._actions_in_run = 0

        if candidate == FarmState.RECOVERY and previous != FarmState.RECOVERY:
            self._recovery_attempts += 1
        if candidate == FarmState.LOOT_RESULT:
            if previous != FarmState.LOOT_RESULT:
                self._loot_result_stabilized = False
            elif action == "wait":
                self._loot_result_stabilized = True
        elif previous == FarmState.LOOT_RESULT:
            self._loot_result_stabilized = False
        # Recovery attempts are session-level, not consecutive-level: a
        # successful-looking escape must not allow an endless recovery loop.
        if self._recovery_attempts > self.max_recovery_attempts:
            raise FarmSafetyStop(
                "Recovery farming berulang terlalu sering; sesi dihentikan."
            )
        self.check()
        return self.state

    def validate_and_advance(
        self,
        next_state: str,
        action: str,
        text: str | None = None,
        coordinate: object | None = None,
    ) -> FarmState:
        """Validate and commit a transition for direct/unit-test callers."""
        return self.advance(self.validate(next_state, action, text, coordinate), action)

    def check(self) -> None:
        """Enter bounded recovery on stagnation; stop if recovery also stalls."""
        elapsed = self._clock() - self._state_started_at
        stalled = (
            elapsed >= self.state_timeout_seconds
            or self._actions_without_transition >= self.max_actions_without_transition
            or self._actions_in_run >= self.max_actions_per_run
        )
        if not stalled:
            return
        if self.state == FarmState.RECOVERY:
            raise FarmSafetyStop(
                "Recovery farming tidak menghasilkan progres dalam batas aman."
            )
        self.state = FarmState.RECOVERY
        self._state_started_at = self._clock()
        self._actions_without_transition = 0
        # Keep _actions_in_run intact. A recovery is not a completed run and
        # must not reset the per-run budget.
        self._recovery_attempts += 1
        if self._recovery_attempts > self.max_recovery_attempts:
            raise FarmSafetyStop(
                "Recovery farming berulang terlalu sering; sesi dihentikan."
            )

    def caption(self) -> str:
        """Return the current state for the next screenshot message."""
        return f"Current screenshot. Farming state: {self.state.value}."


def _is_screen_coordinate(value: object) -> bool:
    """Return whether a model coordinate fits the screenshot bounds."""
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(
            isinstance(component, int)
            and not isinstance(component, bool)
            and 0 <= component < limit
            for component, limit in zip(value, (TARGET_WIDTH, TARGET_HEIGHT))
        )
    )


def farm_state_values() -> tuple[str, ...]:
    """Return stable enum values for the OpenAI-compatible tool schema."""
    return tuple(state.value for state in FarmState)
