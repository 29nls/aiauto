"""Entrypoint: run the bot with ``python -m dn_bot``."""

from __future__ import annotations

import time

from .config import (
    START_DELAY_SECONDS,
    EmergencyStop,
    FocusLost,
    log,
    preflight_configuration,
)
from .orchestrator import run_dn_bot


def main() -> None:
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
        run_dn_bot(
            "Amati screenshot. Jika ada NPC yang jelas terlihat dan aman untuk "
            "didekati, dekati secara perlahan lalu gunakan F untuk interaksi. "
            "Jika tujuan tidak jelas, jangan melakukan aksi.",
        )
    except (EmergencyStop, FocusLost) as error:
        log.warning("Sesi dihentikan: %s", error)
    except KeyboardInterrupt:
        log.info("Sesi dihentikan oleh pengguna (Ctrl+C).")
    except Exception:
        log.exception("Error fatal; tidak ada aksi tambahan yang dijalankan.")


if __name__ == "__main__":
    main()
