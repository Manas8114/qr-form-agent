"""Global atomic kill-switch mechanism."""

import logging
from pathlib import Path
from qr_form_agent.config import settings

logger = logging.getLogger(__name__)

KILL_SWITCH_FILE = Path("./data/KILL_SWITCH_ACTIVE")


class KillSwitchTriggeredError(RuntimeError):
    """Raised when an operation is attempted while the global kill switch is active."""
    pass


def is_kill_switch_active() -> bool:
    """Returns True if global kill switch is triggered."""
    return KILL_SWITCH_FILE.exists()


def activate_kill_switch(reason: str = "Manual operator intervention") -> None:
    """Engages the global kill switch."""
    KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(KILL_SWITCH_FILE, "w", encoding="utf-8") as f:
        f.write(f"ACTIVATED: {reason}\n")
    logger.critical("GLOBAL KILL SWITCH ACTIVATED: %s", reason)


def deactivate_kill_switch() -> None:
    """Disengages the global kill switch."""
    if KILL_SWITCH_FILE.exists():
        KILL_SWITCH_FILE.unlink()
        logger.info("Global kill switch deactivated.")


def enforce_kill_switch() -> None:
    """Raises KillSwitchTriggeredError if kill switch is active."""
    if is_kill_switch_active():
        raise KillSwitchTriggeredError("Operation aborted: Global kill switch is ACTIVE!")
