"""Structured profile synthesizer from resume text via Claude / LLM.

Enforces zero-tool, strict Pydantic JSON schema with rule: 'null if absent, never guess'.
"""

import json
import logging
import re
from typing import Optional
from qr_form_agent.config import settings
from qr_form_agent.profile.schema import Profile

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strict, precise resume parser.
Extract the candidate's verified profile from the provided resume text into a single JSON object.
CRITICAL RULES:
1. Every attribute is nullable. If a field is NOT explicitly mentioned or is ambiguous, set it to null.
2. NEVER guess, extrapolate, or hallucinate. "null if absent, never guess".
3. Return ONLY a valid JSON object matching the requested schema. No markdown formatting, no commentary.
"""


def _build_user_prompt(resume_text: str) -> str:
    schema_json = json.dumps(Profile.model_json_schema(), indent=2)
    return f"""Please extract the candidate's profile from the following resume text into this exact JSON schema:

<schema>
{schema_json}
</schema>

<resume_text>
{resume_text}
</resume_text>

Return ONLY the raw JSON object conforming to the schema.
"""


def synthesize_profile(resume_text: str, api_key: Optional[str] = None) -> Profile:
    """
    Synthesizes a structured Profile object from plain resume text.
    Uses Anthropic Claude if configured, Gemini if configured, or heuristic parser fallback if offline/no key.
    """
    api_key = api_key or settings.anthropic_api_key

    # If Anthropic API key is provided, use Claude
    if api_key and settings.llm_provider == "anthropic":
        return _synthesize_with_claude(resume_text, api_key)

    # If Gemini API key is provided
    if settings.gemini_api_key and settings.llm_provider == "gemini":
        return _synthesize_with_gemini(resume_text, settings.gemini_api_key)

    # Heuristic / offline fallback parser for testing and environments without API key
    logger.info("Using offline heuristic extractor for profile synthesis.")
    return _synthesize_heuristically(resume_text)


def _synthesize_with_claude(resume_text: str, api_key: str) -> Profile:
    """Invokes Anthropic Claude with strict JSON schema instructions and zero tools."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=4096,
            temperature=0.0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(resume_text)}],
        )

        content = response.content[0].text.strip()
        # Strip potential markdown code block fences
        clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
        data = json.loads(clean_json)
        return Profile.model_validate(data)
    except Exception as e:
        logger.error("Claude profile synthesis failed: %s. Falling back to heuristic.", e)
        return _synthesize_heuristically(resume_text)


def _synthesize_with_gemini(resume_text: str, api_key: str) -> Profile:
    """Invokes Google Gemini with structured output."""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\n{_build_user_prompt(resume_text)}",
        )
        content = response.text.strip()
        clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
        data = json.loads(clean_json)
        return Profile.model_validate(data)
    except Exception as e:
        logger.error("Gemini profile synthesis failed: %s. Falling back to heuristic.", e)
        return _synthesize_heuristically(resume_text)


def _synthesize_heuristically(text: str) -> Profile:
    """
    Deterministic regex-based fallback extractor.
    Extracts explicit email, phone, links, and names while respecting 'null if absent, never guess'.
    """
    profile = Profile()

    # Email
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    if email_match:
        profile.email = email_match.group(0)

    # Phone
    phone_match = re.search(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
    if phone_match:
        profile.phone = phone_match.group(0).strip()

    # LinkedIn / GitHub
    li_match = re.search(r"https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+", text)
    if li_match:
        profile.linkedin_url = li_match.group(0)

    gh_match = re.search(r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_-]+", text)
    if gh_match:
        profile.github_url = gh_match.group(0)

    portfolio_match = re.search(r"https?://(?:www\.)?[a-zA-Z0-9-]+\.(?:io|me|dev|app)", text)
    if portfolio_match:
        profile.portfolio_url = portfolio_match.group(0)

    # Full name heuristic: usually top lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        first_line = lines[0]
        # If first line looks like a name (2 to 4 words, alphabetic)
        words = first_line.split()
        if 2 <= len(words) <= 4 and all(w.replace(".", "").isalpha() for w in words):
            profile.full_name = first_line
            profile.first_name = words[0]
            profile.last_name = words[-1]

    # Skills heuristic: look for "Skills:" or "Technical Skills:" section
    skills_match = re.search(r"(?:Technical\s+)?Skills\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE)
    if skills_match:
        raw_skills = skills_match.group(1)
        profile.skills = [s.strip() for s in re.split(r"[,•|;]", raw_skills) if s.strip()]

    return profile
