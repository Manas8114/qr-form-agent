"""SQLite-backed per-domain field mapping cache."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from qr_form_agent.config import settings

logger = logging.getLogger(__name__)


class MappingCache:
    """Manages approved per-domain field mappings in SQLite."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.data_dir / "mapping_cache.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domain_field_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    field_signature TEXT NOT NULL,
                    profile_key TEXT NOT NULL,
                    times_approved INTEGER DEFAULT 1,
                    last_used_at TEXT NOT NULL,
                    UNIQUE(domain, field_signature)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_domain_sig ON domain_field_mappings(domain, field_signature)")
            conn.commit()

    @staticmethod
    def compute_field_signature(tag: str, field_type: str, name: Optional[str], label: str) -> str:
        """Generates a normalized signature for a field on a domain."""
        norm_label = "".join(ch for ch in label.lower() if ch.isalnum() or ch.isspace()).strip()
        norm_name = (name or "").lower().strip()
        return f"{tag.lower()}:{field_type.lower()}:{norm_name}:{norm_label}"

    def get_cached_key(self, domain: str, field_signature: str) -> Optional[str]:
        """Looks up a previously approved profile_key for this domain and signature."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT profile_key FROM domain_field_mappings WHERE domain = ? AND field_signature = ?",
                (domain.lower(), field_signature),
            )
            row = cursor.fetchone()
            if row:
                return str(row["profile_key"])
        return None

    def record_approved_mapping(self, domain: str, field_signature: str, profile_key: str) -> None:
        """Stores or increments an approved mapping in the domain cache."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO domain_field_mappings (domain, field_signature, profile_key, times_approved, last_used_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(domain, field_signature) DO UPDATE SET
                    profile_key = excluded.profile_key,
                    times_approved = times_approved + 1,
                    last_used_at = excluded.last_used_at
            """, (domain.lower(), field_signature, profile_key, now))
            conn.commit()
        logger.debug("Cached approved mapping for %s: %s -> %s", domain, field_signature, profile_key)
