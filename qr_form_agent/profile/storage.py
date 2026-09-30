"""Local storage manager for verified profile.json.

Ensures the resume is parsed once and loaded deterministically across all form jobs.
"""

import json
import logging
from pathlib import Path
from typing import Optional
from qr_form_agent.config import settings
from qr_form_agent.profile.schema import Profile

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_PATH = Path("./data/profiles/verified_profile.json")


def save_verified_profile(profile: Profile, target_path: Optional[Path] = None) -> Path:
    """Save verified profile to local disk."""
    path = target_path or DEFAULT_PROFILE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(profile.model_dump_json(indent=2))
    logger.info("Saved verified profile to %s", path)
    return path


def load_verified_profile(source_path: Optional[Path] = None) -> Optional[Profile]:
    """Load verified profile from local disk if it exists."""
    path = source_path or DEFAULT_PROFILE_PATH
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Profile.model_validate(data)
