"""Saved Answers Bank for recurring standard form questions.

Enforces Requirement 9:
Questions like "Do you need visa sponsorship?", "Notice period?", or "Salary expectation?"
get asked once and stored, then reused deterministically across forms at 1.0 confidence,
completely keeping them out of the untrusted LLM path.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from qr_form_agent.config import settings

logger = logging.getLogger(__name__)


class SavedAnswer(BaseModel):
    key: str = Field(description="Unique answer key identifier")
    category: str = Field(default="general", description="Category: eligibility, logistics, legal, demographic")
    question_text: str = Field(description="Representative question text")
    value: str = Field(description="User's verified answer")
    match_patterns: List[str] = Field(default_factory=list, description="Regex or substring patterns to match against field labels")


DEFAULT_BANK_ITEMS: List[SavedAnswer] = [
    SavedAnswer(
        key="visa_sponsorship",
        category="eligibility",
        question_text="Will you now or in the future require visa sponsorship?",
        value="No",
        match_patterns=[
            r"visa\s+sponsorship",
            r"require\s+(?:any\s+)?sponsorship",
            r"need\s+(?:visa\s+)?sponsorship",
            r"work\s+permit\s+sponsorship",
        ],
    ),
    SavedAnswer(
        key="work_authorization",
        category="eligibility",
        question_text="Are you legally authorized to work in the country of employment?",
        value="Yes",
        match_patterns=[
            r"legally\s+authorized\s+to\s+work",
            r"lawful(?:ly)?\s+authorized",
            r"eligible\s+to\s+work",
            r"right\s+to\s+work",
        ],
    ),
    SavedAnswer(
        key="notice_period",
        category="logistics",
        question_text="What is your current notice period?",
        value="Immediate / 0 days",
        match_patterns=[
            r"notice\s+period",
            r"how\s+much\s+notice",
            r"current\s+notice",
        ],
    ),
    SavedAnswer(
        key="preferred_start_date",
        category="logistics",
        question_text="When are you available to start?",
        value="Immediately",
        match_patterns=[
            r"start\s+date",
            r"available\s+to\s+start",
            r"earliest\s+start",
        ],
    ),
    SavedAnswer(
        key="salary_expectation",
        category="logistics",
        question_text="What are your salary expectations?",
        value="Competitive / Market rate",
        match_patterns=[
            r"salary\s+expectation",
            r"desired\s+salary",
            r"compensation\s+expectation",
            r"expected\s+salary",
        ],
    ),
    SavedAnswer(
        key="willing_to_relocate",
        category="logistics",
        question_text="Are you willing to relocate?",
        value="Yes",
        match_patterns=[
            r"willing\s+to\s+relocate",
            r"relocation",
            r"open\s+to\s+relocat",
        ],
    ),
    SavedAnswer(
        key="referral_source",
        category="general",
        question_text="How did you hear about this position?",
        value="Career Fair / University Job Board",
        match_patterns=[
            r"how\s+did\s+you\s+hear",
            r"referral\s+source",
            r"where\s+did\s+you\s+find",
            r"source\s+of\s+application",
        ],
    ),
    SavedAnswer(
        key="over_18",
        category="legal",
        question_text="Are you 18 years of age or older?",
        value="Yes",
        match_patterns=[
            r"18\s+years\s+of\s+age",
            r"at\s+least\s+18",
            r"are\s+you\s+18",
            r"over\s+the\s+age\s+of\s+18",
        ],
    ),
]


class AnswersBank:
    def __init__(self, storage_path: Optional[Path] = None):
        if storage_path:
            self.storage_path = storage_path
        else:
            self.storage_path = settings.data_dir / "answers_bank.json"

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.answers: Dict[str, SavedAnswer] = {}
        self.load()

    def load(self) -> None:
        """Loads answers from JSON file or initializes defaults."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.answers = {
                        k: SavedAnswer.model_validate(v) for k, v in data.items()
                    }
                return
            except Exception as e:
                logger.warning("Failed to load answers bank from %s: %s", self.storage_path, e)

        # Initialize defaults
        self.answers = {item.key: item for item in DEFAULT_BANK_ITEMS}
        self.save()

    def save(self) -> None:
        """Saves current answers bank to persistent JSON storage."""
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                data = {k: v.model_dump() for k, v in self.answers.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save answers bank to %s: %s", self.storage_path, e)

    def find_answer(self, field_text: str) -> Optional[Tuple[str, str, float]]:
        """
        Checks whether field_text (label, placeholder, or question name)
        matches a known answer in the bank.
        Returns: (answer_key, answer_value, confidence=1.0) or None.
        """
        if not field_text:
            return None

        clean = field_text.lower().strip()
        for answer in self.answers.values():
            for pattern in answer.match_patterns:
                if re.search(pattern, clean, re.IGNORECASE):
                    logger.debug(
                        "[ANSWERS_BANK_HIT] Matched '%s' to answer '%s' (%s)",
                        field_text,
                        answer.key,
                        answer.value,
                    )
                    return (answer.key, answer.value, 1.0)

        return None

    def set_answer(
        self,
        key: str,
        value: str,
        question_text: Optional[str] = None,
        patterns: Optional[List[str]] = None,
        category: str = "general",
        match_patterns: Optional[List[str]] = None,
    ) -> SavedAnswer:
        """Updates or adds an answer in the bank."""
        effective_patterns = patterns or match_patterns
        if key in self.answers:
            item = self.answers[key]
            item.value = value
            if question_text:
                item.question_text = question_text
            if effective_patterns:
                for p in effective_patterns:
                    if p not in item.match_patterns:
                        item.match_patterns.append(p)
        else:
            item = SavedAnswer(
                key=key,
                category=category,
                question_text=question_text or key,
                value=value,
                match_patterns=effective_patterns or [re.escape(key.lower())],
            )
            self.answers[key] = item

        self.save()
        return item

    def all_answers(self) -> List[SavedAnswer]:
        return list(self.answers.values())

    def get_answer(self, key: str) -> Optional[SavedAnswer]:
        """Retrieves a single answer by key if present."""
        return self.answers.get(key)

    def delete_answer(self, key: str) -> bool:
        """Deletes an answer by key and saves changes."""
        if key in self.answers:
            del self.answers[key]
            self.save()
            return True
        return False

    upsert_answer = set_answer
