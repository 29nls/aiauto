"""Entrypoint: run the bot with ``python -m dn_bot``."""

from __future__ import annotations

import argparse
import os
import time

from .config import (
    DEFAULT_INSTRUCTION,
    START_DELAY_SECONDS,
    EmergencyStop,
    FocusLost,
    log,
    preflight_configuration,
)
from .device import DryRunDevice
from .farm import FarmSafetyStop, MINOTAUR_PROFILE
from .orchestrator import run_dn_bot


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments (stdlib argparse)."""
    parser = argparse.ArgumentParser(
        prog="python -m dn_bot",
        description="Vision agent untuk eksperimen kontrol input Dragon Nest.",
    )
    parser.add_argument(
        "--instruction",
        help=(
            "Tujuan sesi. Precedence: flag ini > env DN_INSTRUCTION > teks "
            "bawaan (DEFAULT_INSTRUCTION)."
        ),
    )
    parser.add_argument(
        "--farm-profile",
        choices=[MINOTAUR_PROFILE.name],
        help="Profil farming berkelanjutan yang tersedia (saat ini: minotaur).",
    )
    parser.add_argument(
        "--until-stopped",
        action="store_true",
        help=(
            "Dalam profil farming, ulangi run sampai operator menghentikan "
            "dengan Ctrl+C atau emergency stop."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Mode latihan (rehearsal): jalankan loop penuh (capture -> model -> "
            "aksi -> frame baru) tetapi aksi fisik yang dimaksud hanya di-log "
            "(prefix [dry-run]) dan TIDAK pernah dieksekusi."
        ),
    )
    return parser.parse_args(argv)


def _resolve_instruction(cli_instruction: str | None) -> str:
    """Resolve the session goal: CLI flag > DN_INSTRUCTION env > default text.

    An empty flag/env value is treated as unset, falling back to the next
    precedence level; ``run_dn_bot`` still rejects a non-empty-but-blank
    instruction, so the fail-fast convention is preserved.
    """
    if cli_instruction:
        return cli_instruction
    return os.getenv("DN_INSTRUCTION", "").strip() or DEFAULT_INSTRUCTION


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.until_stopped and not args.farm_profile:
        raise SystemExit("--until-stopped membutuhkan --farm-profile minotaur.")
    instruction = _resolve_instruction(args.instruction)
    print(
        "\nDragon Nest AI Agent\n"
        "Gunakan hanya di lingkungan yang diizinkan oleh Terms of Service game.\n"
        "Emergency stop: gerakkan kursor ke pojok kiri atas atau tekan Ctrl+C.\n"
    )
    if args.dry_run:
        print(
            "MODE DRY-RUN: loop penuh dijalankan tetapi aksi fisik TIDAK akan "
            "dieksekusi — primitif input yang dimaksud hanya di-log ([dry-run]).\n"
        )
    try:
        preflight_configuration()
    except (RuntimeError, ValueError) as error:
        log.error("Preflight gagal: %s", error)
        raise SystemExit(1) from error
    print(f"Fokus jendela game dalam {START_DELAY_SECONDS} detik...")
    for remaining in range(START_DELAY_SECONDS, 0, -1):
        print(f"{remaining}...", flush=True)
        time.sleep(1)

    try:
        profile = MINOTAUR_PROFILE if args.farm_profile == MINOTAUR_PROFILE.name else None
        kwargs = {
            "farm_profile": profile,
            "until_stopped": args.until_stopped,
        }
        if args.dry_run:
            # Rehearsal: same session path, but the injected device logs the
            # intended physical actions instead of performing them.
            run_dn_bot(instruction, device=DryRunDevice(), **kwargs)
        elif profile is not None:
            run_dn_bot(instruction, **kwargs)
        else:
            # Byte-identical no-args path: production adapter is the default.
            run_dn_bot(instruction)
    except (EmergencyStop, FocusLost, FarmSafetyStop) as error:
        log.warning("Sesi dihentikan: %s", error)
    except KeyboardInterrupt:
        log.info("Sesi dihentikan oleh pengguna (Ctrl+C).")
    except Exception:
        log.exception("Error fatal; tidak ada aksi tambahan yang dijalankan.")


if __name__ == "__main__":
    main()
