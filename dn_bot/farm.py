"""Supervised Minotaur farming profile and progress watchdog.

This module contains no API, capture, or device imports. It owns only the
workflow contract: states, legal transitions, per-state action policy, and
progress limits. The orchestrator remains responsible for I/O and executes at
most one validated action per fresh screenshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
import time
from typing import FrozenSet, Mapping

from .config import (
    TARGET_HEIGHT,
    TARGET_WIDTH,
    validate_retreat_destination,
)


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


_FARM_ACTION_VALUES = (
    "mouse_move",
    "left_click",
    "right_click",
    "press_move_key",
    "press_action_key",
    "move_camera",
    "wait",
)
_FARM_ACTIONS = frozenset(_FARM_ACTION_VALUES)


@dataclass(frozen=True)
class FarmPhasePolicy:
    """Declarative actions for each legal next state in one phase."""

    actions_by_next_state: Mapping[FarmState, FrozenSet[str]]
    required_key: str | None = None
    requires_stable_wait: bool = False
    click_labels: tuple[str, ...] = ()
    coordinate_required: bool = False

    @property
    def transitions(self) -> FrozenSet[FarmState]:
        return frozenset(self.actions_by_next_state)

    @property
    def allowed_actions(self) -> FrozenSet[str]:
        return frozenset(
            action
            for actions in self.actions_by_next_state.values()
            for action in actions
        )


MINOTAUR_PHASE_POLICY: Mapping[FarmState, FarmPhasePolicy] = MappingProxyType({
    FarmState.PRE_DUNGEON: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.PRE_DUNGEON: frozenset({"left_click", "mouse_move", "wait"}),
                FarmState.ENTERING_DUNGEON: frozenset({"left_click", "mouse_move", "wait"}),
                FarmState.RECOVERY: frozenset({"left_click", "mouse_move", "wait"}),
            }
        ),
    ),
    FarmState.ENTERING_DUNGEON: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.ENTERING_DUNGEON: _FARM_ACTIONS,
                FarmState.COMBAT: _FARM_ACTIONS,
                FarmState.RECOVERY: _FARM_ACTIONS,
            }
        ),
    ),
    FarmState.COMBAT: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.COMBAT: _FARM_ACTIONS,
                FarmState.BOSS_REWARD: _FARM_ACTIONS,
                FarmState.RECOVERY: _FARM_ACTIONS,
            }
        ),
    ),
    FarmState.BOSS_REWARD: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.BOSS_REWARD: frozenset({"wait"}),
                FarmState.LOOT_CHEST: frozenset({"wait"}),
                FarmState.RECOVERY: frozenset({"wait"}),
            }
        ),
    ),
    FarmState.LOOT_CHEST: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.LOOT_CHEST: frozenset({"left_click", "mouse_move", "wait"}),
                FarmState.LOOT_RESULT: frozenset({"left_click", "mouse_move", "wait"}),
                FarmState.RECOVERY: frozenset({"left_click", "mouse_move", "wait"}),
            }
        ),
    ),
    FarmState.LOOT_RESULT: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.LOOT_RESULT: frozenset({"wait"}),
                FarmState.RETREAT_DIALOG: frozenset({"press_action_key"}),
                FarmState.RECOVERY: frozenset({"wait"}),
            }
        ),
        required_key="f12",
        requires_stable_wait=True,
    ),
    FarmState.RETREAT_DIALOG: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.RETREAT_DIALOG: frozenset({"wait"}),
                FarmState.RETURN_WAIT: frozenset({"left_click"}),
                FarmState.RECOVERY: frozenset({"wait"}),
            }
        ),
        click_labels=("town", "stage entrance"),
        coordinate_required=True,
    ),
    FarmState.RETURN_WAIT: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.RETURN_WAIT: frozenset({"wait"}),
                FarmState.PRE_DUNGEON: frozenset({"wait"}),
                FarmState.RECOVERY: frozenset({"wait"}),
            }
        ),
    ),
    FarmState.RECOVERY: FarmPhasePolicy(
        actions_by_next_state=MappingProxyType(
            {
                FarmState.RECOVERY: frozenset({"press_action_key", "wait"}),
                FarmState.PRE_DUNGEON: frozenset({"wait"}),
            }
        ),
        required_key="f12",
    ),
})


@dataclass(frozen=True)
class FarmObservationClaim:
    """Untrusted model claim about the state after its proposed action."""

    claimed_state: FarmState
    text: str | None = None
    coordinate: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.claimed_state, FarmState):
            raise FarmSafetyStop(
                "Klaim state farming tidak valid; sesi dihentikan."
            )

    @classmethod
    def from_wire(
        cls,
        next_state: object,
        text: str | None = None,
        coordinate: object | None = None,
    ) -> "FarmObservationClaim":
        """Parse the model state without changing the authoritative workflow."""
        try:
            claimed_state = FarmState(next_state)
        except (TypeError, ValueError) as error:
            raise FarmSafetyStop(
                "Model mengirim farm_state yang tidak dikenal; sesi dihentikan."
            ) from error
        return cls(
            claimed_state=claimed_state,
            text=text,
            coordinate=coordinate,
        )


@dataclass(frozen=True)
class FarmProfile:
    """Static workflow contract for a supported farming target."""

    name: str
    system_prompt: str
    instruction_suffix: str
    initial_state: FarmState
    phase_policy: Mapping[FarmState, FarmPhasePolicy]

    @property
    def allowed_actions(self) -> dict[FarmState, FrozenSet[str]]:
        return {
            state: phase.allowed_actions for state, phase in self.phase_policy.items()
        }

    @property
    def transitions(self) -> dict[FarmState, FrozenSet[FarmState]]:
        return {
            state: phase.transitions for state, phase in self.phase_policy.items()
        }


def farm_policy_prompt(
    phase_policy: Mapping[FarmState, FarmPhasePolicy],
) -> str:
    """Render a phase policy for a farming system prompt."""
    lines = ["Kontrak phase farming yang berasal dari policy:"]
    for state, phase in phase_policy.items():
        actions = ", ".join(sorted(phase.allowed_actions))
        transitions = ", ".join(
            target.value
            for target in sorted(phase.transitions, key=lambda item: item.value)
        )
        rules = []
        if phase.required_key:
            rules.append(f"key {phase.required_key} only")
        if phase.requires_stable_wait:
            rules.append("requires a stable loot wait")
        if phase.click_labels:
            rules.append(
                "retreat label candidates "
                + ", ".join(label.title() for label in phase.click_labels)
            )
        if phase.coordinate_required:
            rules.append("requires a screenshot coordinate")
        rules.append(
            "next state actions "
            + "; ".join(
                f"{target.value}: {', '.join(sorted(actions))}"
                for target, actions in phase.actions_by_next_state.items()
            )
        )
        suffix = f" rules [{'; '.join(rules)}]." if rules else "."
        lines.append(
            f"- {state.value}: actions [{actions}], next states [{transitions}]{suffix}"
        )
    return "\n".join(lines)


_LOOT_EXIT_KEY = MINOTAUR_PHASE_POLICY[FarmState.LOOT_RESULT].required_key or "f12"
_RETREAT_LABELS = tuple(
    label.title()
    for label in MINOTAUR_PHASE_POLICY[FarmState.RETREAT_DIALOG].click_labels
)
_RETREAT_LABEL_TEXT = " atau ".join(_RETREAT_LABELS)
_RETREAT_LABEL_SLASH = "/".join(_RETREAT_LABELS)


MINOTAUR_PROFILE = FarmProfile(
    name="minotaur",
    initial_state=FarmState.PRE_DUNGEON,
    phase_policy=MINOTAUR_PHASE_POLICY,
    instruction_suffix=(
        "\n\nProfil farming Minotaur berkelanjutan aktif. Jalankan run berulang "
        "sampai operator menghentikan sesi. Jangan menganggap farm selesai hanya "
        "karena satu aksi berhasil."
    ),
    system_prompt=(
        "\n\nMODE WORKFLOW MINOTAUR (untrusted screenshot tetap berlaku):\n"
        "Kamu wajib menyertakan field `farm_state` pada setiap tool call. Nilai "
        "state dan transisinya mengikuti kontrak berikut. Nilai itu adalah state "
        "layar SETELAH aksi yang kamu usulkan. Jika tidak yakin, gunakan recovery "
        f"dan hanya wait atau press_action_key {_LOOT_EXIT_KEY}.\n"
        + farm_policy_prompt(MINOTAUR_PHASE_POLICY)
        + "\nState boleh tetap sama. Transisi lain harus dianggap tidak aman.\n"
        "Pada entering_dungeon, gunakan press_action_key 'enter' untuk "
        "konfirmasi dialog — jangan klik koordinat tombol. "
        "Setelah boss mati, jangan memilih box atau melakukan review; tunggu sampai "
        "peti harta di map terlihat jelas. Pada loot_chest, klik hanya peti yang "
        f"jelas terlihat. Setelah loot result stabil dan {_LOOT_EXIT_KEY.upper()} terlihat, "
        f"gunakan press_action_key dengan text {_LOOT_EXIT_KEY} untuk membuka dialog "
        f"{_RETREAT_LABEL_TEXT} dan laporkan retreat_dialog. Pada retreat_dialog, "
        "klik hanya opsi yang terlihat jelas dan diizinkan konfigurasi operator "
        f"(label umum: {_RETREAT_LABEL_TEXT}) atau wait; jangan menekan "
        f"{_LOOT_EXIT_KEY.upper()} lagi. Python menolak label yang tidak cocok "
        "dengan tujuan operator. "
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
        retreat_destination: str | None = None,
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
        self.retreat_destination = validate_retreat_destination(retreat_destination)
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
        """Validate a legacy wire claim without mutating workflow state."""
        return self.validate_claim(
            FarmObservationClaim.from_wire(next_state, text, coordinate),
            action,
        )

    def validate_claim(
        self,
        claim: FarmObservationClaim,
        action: str,
    ) -> FarmState:
        """Validate a model claim without mutating workflow state."""
        candidate = claim.claimed_state
        text = claim.text
        coordinate = claim.coordinate

        phase = self.profile.phase_policy[self.state]
        if candidate not in phase.transitions:
            raise FarmSafetyStop(
                f"Transisi farming tidak aman: {self.state.value} -> {candidate.value}."
            )
        if not isinstance(action, str):
            raise FarmSafetyStop(
                "Model mengirim action yang kosong atau bukan teks; sesi dihentikan."
            )
        if self.state == FarmState.RETREAT_DIALOG and action == "press_action_key":
            raise FarmSafetyStop(
                f"Dialog retreat tidak boleh menekan {_LOOT_EXIT_KEY.upper()}; "
                f"pilih {_RETREAT_LABEL_TEXT}."
            )
        allowed_actions = phase.actions_by_next_state.get(candidate, frozenset())
        if action not in allowed_actions:
            if self.state == FarmState.RECOVERY and candidate == FarmState.PRE_DUNGEON:
                raise FarmSafetyStop(
                    "Recovery hanya boleh melaporkan pre_dungeon setelah wait "
                    "berhasil dan layar baru terkonfirmasi."
                )
            if phase.click_labels or phase.coordinate_required:
                raise FarmSafetyStop(
                    "Dialog retreat hanya boleh wait atau klik "
                    f"{_RETREAT_LABEL_SLASH}."
                )
            raise FarmSafetyStop(
                f"Aksi {action!r} tidak diizinkan pada state {self.state.value}."
            )
        normalized_text = (
            " ".join(text.casefold().split()) if isinstance(text, str) else ""
        )
        if phase.required_key and action == "press_action_key":
            if normalized_text != phase.required_key:
                raise FarmSafetyStop(
                    f"Navigasi farming hanya boleh menekan press_action_key {_LOOT_EXIT_KEY}."
                )
            if phase.requires_stable_wait and not self._loot_result_stabilized:
                raise FarmSafetyStop(
                    "Loot belum stabil; lakukan wait di loot_result sebelum menekan F12."
                )
        if phase.click_labels or phase.coordinate_required:
            if action == "wait" and candidate in {
                self.state,
                FarmState.RECOVERY,
            }:
                return candidate
            if action == "left_click" and candidate == FarmState.RETURN_WAIT:
                if (
                    not phase.coordinate_required or _is_screen_coordinate(coordinate)
                ) and normalized_text in phase.click_labels:
                    if (
                        self.retreat_destination is not None
                        and normalized_text != self.retreat_destination.replace("_", " ")
                    ):
                        raise FarmSafetyStop(
                            "Tujuan retreat tidak cocok dengan konfigurasi operator."
                        )
                    return candidate
                raise FarmSafetyStop(
                    f"Dialog retreat hanya boleh klik opsi {_RETREAT_LABEL_TEXT} "
                    "yang terlihat jelas."
                )
            raise FarmSafetyStop(
                "Dialog retreat hanya boleh wait atau klik "
                f"{_RETREAT_LABEL_SLASH}."
            )
        return candidate

    def ensure_action_allowed(self, candidate: FarmState | None = None) -> None:
        """Reject the next physical action before it can be executed."""
        if self._actions_without_transition >= self.max_actions_without_transition:
            raise FarmSafetyStop(
                f"State {self.state.value} tidak menunjukkan progres setelah "
                f"{self.max_actions_without_transition} aksi."
            )
        # Recovery must be able to spend its own bounded wait actions even
        # when the failed run already exhausted its action budget. The
        # no-progress budget and recovery-attempt limit still bound this path.
        if self.state != FarmState.RECOVERY and self._actions_in_run >= self.max_actions_per_run:
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
            or (
                self.state != FarmState.RECOVERY
                and self._actions_in_run >= self.max_actions_per_run
            )
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
    """Return state values in the policy's declared order."""
    return tuple(state.value for state in MINOTAUR_PHASE_POLICY)


def farm_action_values() -> tuple[str, ...]:
    """Return canonical actions that at least one policy phase permits."""
    permitted = {
        action
        for phase in MINOTAUR_PHASE_POLICY.values()
        for action in phase.allowed_actions
    }
    return tuple(action for action in _FARM_ACTION_VALUES if action in permitted)
