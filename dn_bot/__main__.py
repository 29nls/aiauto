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
    instruction = _resolve_instruction(args.instruction)
    print(
        "\nDragon Nest AI Agent\n"
        "Gunakan hanya di lingkungan yang diizinkan oleh Terms of Service game.\n"
        "Emergency stop: gerakkan kursor ke pojok kiri atas atau tekan Ctrl+C.\n"
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
        run_dn_bot(instruction)
    except (EmergencyStop, FocusLost) as error:
        log.warning("Sesi dihentikan: %s", error)
    except KeyboardInterrupt:
        log.info("Sesi dihentikan oleh pengguna (Ctrl+C).")
    except Exception:
        log.exception("Error fatal; tidak ada aksi tambahan yang dijalankan.")


if __name__ == "__main__":
    main()
