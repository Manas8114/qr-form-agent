"""Structured profile synthesizer from resume text via Claude / LLM.

Enforces zero-tool, strict Pydantic JSON schema with rule: 'null if absent, never guess'.
"""

import json
import logging
import re
from typing import List, Optional, Tuple
from qr_form_agent.config import settings
from qr_form_agent.profile.schema import (
    EducationItem,
    ExperienceItem,
    LinkItem,
    Profile,
    ProjectItem,
)

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


# ---------------------------------------------------------------------------
# Comprehensive section-aware heuristic resume parser
# ---------------------------------------------------------------------------

# Section header patterns (case-insensitive)
_SECTION_HEADERS = {
    "summary": re.compile(
        r"^(?:professional\s+)?(?:summary|objective|about\s+me|profile|career\s+overview)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "education": re.compile(
        r"^education(?:al)?\s*(?:background|history|qualifications?)?\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "experience": re.compile(
        r"^(?:work\s+|professional\s+)?(?:experience|employment|work\s+history|career\s+history)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "skills": re.compile(
        r"^(?:technical\s+|core\s+|key\s+|relevant\s+)?skills?\s*(?:&\s*(?:tools|technologies))?\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "projects": re.compile(
        r"^(?:personal\s+|academic\s+|notable\s+)?projects?\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "certifications": re.compile(
        r"^(?:certifications?|licenses?|credentials?)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "awards": re.compile(
        r"^(?:awards?|honors?|achievements?)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "publications": re.compile(
        r"^(?:publications?|research)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "languages": re.compile(
        r"^(?:languages?)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "interests": re.compile(
        r"^(?:hobbies|interests?|activities)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
    "references": re.compile(
        r"^(?:references?)\s*[:\-–—]?\s*$",
        re.IGNORECASE,
    ),
}

# Date pattern used across sections
_DATE_PATTERN = re.compile(
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s*\.?\s*\d{2,4}|\d{1,2}/\d{2,4}|\d{4}|Present|Current|Ongoing|Now)",
    re.IGNORECASE,
)

_DATE_RANGE_PATTERN = re.compile(
    r"(" + _DATE_PATTERN.pattern + r")"
    r"\s*(?:[-–—]|to)\s*"
    r"(" + _DATE_PATTERN.pattern + r")",
    re.IGNORECASE,
)

# Phone patterns (international)
_PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?"  # optional country code
    r"(?:\(?\d{2,4}\)?[\s.-]?)?"  # optional area code
    r"\d{3,5}[\s.-]?\d{3,5}"  # main number
    r"(?:\s*(?:ext|x)\.?\s*\d{1,5})?",  # optional extension
    re.IGNORECASE,
)

# Degree patterns
_DEGREE_PATTERN = re.compile(
    r"(?:Bachelor(?:'?s)?|B\.?(?:S|A|E|Tech|Eng|Sc|Com|B\.A)\.?|"
    r"Master(?:'?s)?|M\.?(?:S|A|Tech|Eng|Sc|B\.A|Phil)\.?|"
    r"(?:Doctor(?:ate)?|Ph\.?D\.?)|"
    r"Associate(?:'?s)?|A\.?(?:S|A)\.?|"
    r"M\.?B\.?A\.?|"
    r"Diploma|Certificate|"
    r"B\.?C\.?A\.?|M\.?C\.?A\.?|B\.?E\.?|M\.?E\.?)",
    re.IGNORECASE,
)

# Indian states for address parsing
_INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya",
    "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim",
    "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand",
    "west bengal", "delhi", "new delhi",
}

# US states abbreviations
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

_COUNTRIES = {
    "india", "united states", "usa", "us", "united kingdom", "uk", "canada",
    "australia", "germany", "france", "singapore", "japan", "china", "brazil",
    "netherlands", "ireland", "sweden", "norway", "switzerland", "denmark",
    "new zealand", "south korea", "israel", "uae", "dubai",
}


def _detect_sections(lines: List[str]) -> List[Tuple[str, int, int]]:
    """
    Splits the resume text into (section_name, start_line, end_line) tuples.
    Lines before the first recognized header are labeled 'header'.
    """
    sections: List[Tuple[str, int]] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        for sec_name, pattern in _SECTION_HEADERS.items():
            if pattern.match(stripped):
                sections.append((sec_name, i))
                break

    if not sections:
        return [("header", 0, len(lines))]

    result: List[Tuple[str, int, int]] = []
    # Everything before the first section header is 'header'
    if sections[0][1] > 0:
        result.append(("header", 0, sections[0][1]))

    for idx, (name, start) in enumerate(sections):
        end = sections[idx + 1][1] if idx + 1 < len(sections) else len(lines)
        result.append((name, start, end))

    return result


def _extract_email(text: str) -> Optional[str]:
    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return m.group(0) if m else None


def _extract_phone(text: str) -> Optional[str]:
    """Extract phone number, filtering out things that look like dates or zip codes."""
    for m in _PHONE_PATTERN.finditer(text):
        candidate = m.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        # Phone numbers have 7-15 digits; skip if too short (zip code) or too long
        if 7 <= len(digits) <= 15:
            return candidate
    return None


def _extract_links(text: str) -> Tuple[Optional[str], Optional[str], Optional[str], List[LinkItem]]:
    """Extract LinkedIn, GitHub, portfolio, and other links from text."""
    linkedin = None
    github = None
    portfolio = None
    others: List[LinkItem] = []

    urls = re.findall(r"https?://[^\s,;\"'<>)\]]+", text)
    for url in urls:
        url_clean = url.rstrip(".")
        low = url_clean.lower()
        if "linkedin.com" in low:
            linkedin = url_clean
        elif "github.com" in low:
            github = url_clean
        elif any(ext in low for ext in (".io", ".me", ".dev", ".app", ".com/portfolio", "portfolio")):
            portfolio = url_clean
        else:
            others.append(LinkItem(label="Link", url=url_clean))

    return linkedin, github, portfolio, others


def _extract_name(header_lines: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract full_name, first_name, last_name from the header portion.
    The name is typically the first non-empty line that looks like a name.
    """
    for line in header_lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip lines that look like contact info
        if "@" in stripped or "http" in stripped.lower() or re.match(r"^[\d\+\(\)]", stripped):
            continue
        # Skip lines that are section headers
        is_header = False
        for pattern in _SECTION_HEADERS.values():
            if pattern.match(stripped):
                is_header = True
                break
        if is_header:
            continue

        words = stripped.split()
        # Name: 1-4 words, mostly alphabetic
        if 1 <= len(words) <= 5 and all(
            w.replace(".", "").replace("-", "").replace("'", "").isalpha() for w in words
        ):
            full = stripped
            first = words[0]
            last = words[-1] if len(words) > 1 else None
            return full, first, last

    return None, None, None


def _extract_address(header_text: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extract address, city, state, postal_code, country from header text.
    Returns (address, city, state, postal_code, country).
    """
    city = None
    state = None
    postal_code = None
    country = None
    address = None

    lines = header_text.splitlines()

    for line in lines:
        stripped = line.strip()
        low = stripped.lower()

        # Skip empty, email, phone, URL, or name-like lines
        if not stripped or "@" in stripped or "http" in low:
            continue

        # Look for postal / zip code
        zip_match = re.search(r"\b(\d{5,6}(?:-\d{4})?)\b", stripped)
        if zip_match:
            postal_code = zip_match.group(1)

        # Look for Indian states
        for ist in _INDIAN_STATES:
            if ist in low:
                state = ist.title()
                break

        # Look for US state abbreviations
        state_match = re.search(r"\b([A-Z]{2})\b", stripped)
        if state_match and state_match.group(1) in _US_STATES:
            state = state_match.group(1)

        # Look for countries
        for c in _COUNTRIES:
            if c in low:
                country = c.title()
                break

        # If the line has commas and looks like an address
        if "," in stripped:
            parts = [p.strip() for p in stripped.split(",")]
            # Try to identify city from comma-separated parts
            for part in parts:
                part_low = part.lower()
                # Skip if it's a state or country we already found
                if state and part_low == state.lower():
                    continue
                if country and part_low == country.lower():
                    continue
                # Skip zip codes
                if re.match(r"^\d{5,6}(?:-\d{4})?$", part):
                    continue
                # This could be a city
                if not city and len(part) > 1 and part[0].isupper():
                    city = part

            # If the line has address-like structure (number + street)
            if re.search(r"\d+\s+\w+", stripped):
                address = stripped

    return address, city, state, postal_code, country


def _parse_education_section(lines: List[str]) -> List[EducationItem]:
    """Parse education section into structured EducationItem list."""
    items: List[EducationItem] = []
    current: Optional[dict] = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip section header itself
        if _SECTION_HEADERS["education"].match(stripped):
            continue

        # Look for date range on this line
        date_match = _DATE_RANGE_PATTERN.search(stripped)
        degree_match = _DEGREE_PATTERN.search(stripped)

        # Lines with a degree or institution often start a new education entry
        has_degree = degree_match is not None
        has_dates = date_match is not None

        # Heuristic: if the line contains a degree keyword or is a new institution line
        # (starts with uppercase and has more than 2 words), it's a new entry
        words = stripped.split()
        looks_like_institution = (
            len(words) >= 2
            and stripped[0].isupper()
            and not stripped.startswith(("•", "-", "*", "–", "—"))
            and (has_degree or has_dates or any(
                kw in stripped.lower()
                for kw in ("university", "college", "institute", "school", "academy", "iit", "nit", "iiit")
            ))
        )

        if looks_like_institution:
            # Save previous entry
            if current:
                items.append(EducationItem(**current))

            current = {
                "institution": None,
                "degree": None,
                "field_of_study": None,
                "start_year": None,
                "end_year": None,
                "gpa": None,
            }

            # Extract degree
            if degree_match:
                current["degree"] = degree_match.group(0).strip()

            # Extract dates
            if date_match:
                current["start_year"] = date_match.group(1).strip()
                current["end_year"] = date_match.group(2).strip()

            # Extract institution: remove the degree and date parts
            inst_text = stripped
            if date_match:
                inst_text = inst_text[:date_match.start()] + inst_text[date_match.end():]
            if degree_match:
                inst_text = inst_text[:degree_match.start()] + inst_text[degree_match.end():]
            # Clean separators
            inst_text = re.sub(r"\s*[-–—|,]\s*$", "", inst_text).strip()
            inst_text = re.sub(r"^\s*[-–—|,]\s*", "", inst_text).strip()
            inst_text = re.sub(r"\s*\(\s*\)\s*", "", inst_text).strip()

            if inst_text:
                current["institution"] = inst_text

            # Try to find field of study
            field_match = re.search(
                r"(?:in|of)\s+(.+?)(?:\s*[-–—(,]|$)",
                stripped,
                re.IGNORECASE,
            )
            if field_match:
                field = field_match.group(1).strip().rstrip(".,;")
                # Don't assign if it looks like a date
                if not re.match(r"^\d{4}$", field) and len(field) > 2:
                    current["field_of_study"] = field

        elif current:
            # Continuation line: could contain GPA, field of study, or other info
            gpa_match = re.search(
                r"(?:GPA|CGPA|Grade|Percentage)\s*[:\s]*([0-9]+\.?[0-9]*(?:\s*/\s*[0-9]+\.?[0-9]*)?%?)",
                stripped,
                re.IGNORECASE,
            )
            if gpa_match:
                current["gpa"] = gpa_match.group(1).strip()

            # If no degree yet, check continuation for degree
            if not current["degree"]:
                dm = _DEGREE_PATTERN.search(stripped)
                if dm:
                    current["degree"] = dm.group(0).strip()

            # If no field yet, check for "Computer Science", "Mechanical Engineering" patterns
            if not current["field_of_study"]:
                field_kw = re.search(
                    r"(?:Computer\s+Science|Electrical|Mechanical|Civil|Chemical|"
                    r"Information\s+Technology|Data\s+Science|Artificial\s+Intelligence|"
                    r"Mathematics|Physics|Chemistry|Biology|Economics|Business|"
                    r"Software\s+Engineering|Electronics|Communication|Commerce|"
                    r"Arts|Science|Engineering|Technology|Management)",
                    stripped,
                    re.IGNORECASE,
                )
                if field_kw:
                    current["field_of_study"] = field_kw.group(0).strip()

            # If no dates yet, check continuation
            if not current["start_year"]:
                dm2 = _DATE_RANGE_PATTERN.search(stripped)
                if dm2:
                    current["start_year"] = dm2.group(1).strip()
                    current["end_year"] = dm2.group(2).strip()

    # Don't forget the last entry
    if current:
        items.append(EducationItem(**current))

    return items


def _parse_experience_section(lines: List[str]) -> List[ExperienceItem]:
    """Parse experience section into structured ExperienceItem list."""
    items: List[ExperienceItem] = []
    current: Optional[dict] = None
    desc_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_HEADERS["experience"].match(stripped):
            continue

        date_match = _DATE_RANGE_PATTERN.search(stripped)
        is_bullet = stripped.startswith(("•", "-", "*", "–", "—", "▪", "▸", "►"))

        # Heuristic: a non-bullet line with dates or a title-like structure starts a new entry
        looks_like_entry_start = (
            not is_bullet
            and (date_match or any(sep in stripped for sep in (" - ", " – ", " — ", " | ", " at ")))
            and stripped[0].isupper()
            and len(stripped.split()) >= 2
        )

        if looks_like_entry_start:
            # Save previous
            if current:
                current["description"] = "\n".join(desc_lines).strip() or None
                items.append(ExperienceItem(**current))
                desc_lines = []

            current = {
                "company": None,
                "title": None,
                "location": None,
                "start_date": None,
                "end_date": None,
                "is_current": None,
                "description": None,
            }

            # Extract dates
            if date_match:
                current["start_date"] = date_match.group(1).strip()
                end_val = date_match.group(2).strip()
                current["end_date"] = end_val
                if end_val.lower() in ("present", "current", "ongoing", "now"):
                    current["is_current"] = True

            # Remove dates from line for parsing title/company
            clean_line = stripped
            if date_match:
                clean_line = (clean_line[:date_match.start()] + clean_line[date_match.end():]).strip()
            clean_line = re.sub(r"[\(\)]", "", clean_line).strip()

            # Try "Title - Company" or "Title at Company" or "Title | Company" patterns
            sep_match = re.split(r"\s+[-–—|]\s+|\s+at\s+", clean_line, maxsplit=1)
            if len(sep_match) == 2:
                current["title"] = sep_match[0].strip().rstrip(",.")
                current["company"] = sep_match[1].strip().rstrip(",.")
            elif len(sep_match) == 1:
                # Single item: could be title or company — take as title, next line might be company
                current["title"] = clean_line.rstrip(",.")

        elif current and is_bullet:
            # Bullet point: description content
            bullet_text = re.sub(r"^[•\-*–—▪▸►]\s*", "", stripped)
            desc_lines.append(f"• {bullet_text}")

        elif current and not is_bullet and stripped:
            # Non-bullet continuation: could be a company name or location on a separate line
            if not current["company"] and stripped[0].isupper():
                # Check if it looks like a company (not a common description word)
                if not any(stripped.lower().startswith(w) for w in ("responsible", "developed", "managed", "led", "built", "designed", "created", "implemented")):
                    current["company"] = stripped.rstrip(",.")
                    continue
            desc_lines.append(stripped)

    # Save last entry
    if current:
        current["description"] = "\n".join(desc_lines).strip() or None
        items.append(ExperienceItem(**current))

    return items


def _parse_projects_section(lines: List[str]) -> List[ProjectItem]:
    """Parse projects section into structured ProjectItem list."""
    items: List[ProjectItem] = []
    current: Optional[dict] = None
    desc_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_HEADERS["projects"].match(stripped):
            continue

        is_bullet = stripped.startswith(("•", "-", "*", "–", "—", "▪", "▸", "►"))

        # Non-bullet line that starts with uppercase → likely a new project
        if not is_bullet and stripped[0].isupper() and len(stripped.split()) >= 1:
            # Save previous
            if current:
                current["description"] = "\n".join(desc_lines).strip() or None
                items.append(ProjectItem(**current))
                desc_lines = []

            current = {
                "name": None,
                "description": None,
                "technologies": [],
                "link": None,
            }

            # Extract any URL on the project line
            url_match = re.search(r"https?://[^\s,;\"'<>)\]]+", stripped)
            if url_match:
                current["link"] = url_match.group(0).rstrip(".")
                stripped = stripped[:url_match.start()].strip()

            # Clean separators
            name = re.sub(r"\s*[-–—|]\s*$", "", stripped).strip()
            name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
            current["name"] = name if name else stripped

        elif current and is_bullet:
            bullet_text = re.sub(r"^[•\-*–—▪▸►]\s*", "", stripped)
            desc_lines.append(f"• {bullet_text}")

            # Extract technologies from "Tech stack: ..." or "Built with ..." bullets
            tech_match = re.search(
                r"(?:Tech(?:nolog(?:y|ies))?\s*(?:stack|used)?|Built\s+with|Tools?|Using)\s*[:\s]+(.+)",
                bullet_text,
                re.IGNORECASE,
            )
            if tech_match:
                techs = re.split(r"[,;|•]", tech_match.group(1))
                current["technologies"].extend(t.strip() for t in techs if t.strip())

        elif current:
            desc_lines.append(stripped)

    if current:
        current["description"] = "\n".join(desc_lines).strip() or None
        items.append(ProjectItem(**current))

    return items


def _parse_skills(lines: List[str]) -> List[str]:
    """Parse skills section into a flat list of skill strings."""
    skills: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_HEADERS["skills"].match(stripped):
            continue

        # Remove common prefixes like "Programming Languages:", "Tools:", etc.
        cleaned = re.sub(
            r"^(?:Programming\s+Languages?|Languages?|Frameworks?|Tools?|"
            r"Databases?|Cloud|DevOps|Libraries|Platforms?|Other|Soft\s+Skills?|"
            r"Technologies|Frontend|Backend|Full\s*Stack)\s*[:\-–—]\s*",
            "",
            stripped,
            flags=re.IGNORECASE,
        ).strip()

        if not cleaned:
            continue

        # Remove bullet prefixes
        cleaned = re.sub(r"^[•\-*▪▸►]\s*", "", cleaned)

        # Split by common delimiters
        raw_skills = re.split(r"[,;|•·]", cleaned)
        for s in raw_skills:
            s = s.strip().strip(".")
            if s and len(s) < 60:  # Skip very long strings that aren't skill names
                skills.append(s)

    return skills


def _extract_summary(lines: List[str]) -> Optional[str]:
    """Extract summary/objective text."""
    parts = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_HEADERS["summary"].match(stripped):
            continue
        parts.append(stripped)

    text = " ".join(parts).strip()
    return text if text else None


def _synthesize_heuristically(text: str) -> Profile:
    """
    Comprehensive deterministic regex-based resume parser.
    Section-aware: detects section headers and delegates to specialized parsers
    for education, experience, projects, skills, and contact info.
    Respects 'null if absent, never guess'.
    """
    profile = Profile()
    lines = text.splitlines()

    # 1. Detect sections
    sections = _detect_sections(lines)

    # 2. Extract global contact info from entire text
    profile.email = _extract_email(text)
    profile.phone = _extract_phone(text)

    linkedin, github, portfolio, other_links = _extract_links(text)
    profile.linkedin_url = linkedin
    profile.github_url = github
    profile.portfolio_url = portfolio
    if other_links:
        profile.other_links = other_links

    # 3. Process each section
    for sec_name, start, end in sections:
        sec_lines = lines[start:end]

        if sec_name == "header":
            # Extract name from header
            full, first, last = _extract_name(sec_lines)
            profile.full_name = full
            profile.first_name = first
            profile.last_name = last

            # Extract address/location from header
            header_text = "\n".join(sec_lines)
            address, city, state, postal_code, country = _extract_address(header_text)
            profile.address = address
            profile.city = city
            profile.state = state
            profile.postal_code = postal_code
            profile.country = country

        elif sec_name == "summary":
            profile.summary = _extract_summary(sec_lines)

        elif sec_name == "education":
            profile.education = _parse_education_section(sec_lines)

        elif sec_name == "experience":
            profile.experience = _parse_experience_section(sec_lines)

        elif sec_name == "skills":
            profile.skills = _parse_skills(sec_lines)

        elif sec_name == "projects":
            profile.projects = _parse_projects_section(sec_lines)

    # 4. If skills were found inline (e.g. "Technical Skills: X, Y, Z" on a single
    #    line in the header) and not via a section, try to extract them
    if not profile.skills:
        skills_match = re.search(
            r"(?:Technical\s+)?Skills\s*[:\n]\s*([^\n]+)", text, re.IGNORECASE
        )
        if skills_match:
            raw_skills = skills_match.group(1)
            profile.skills = [
                s.strip() for s in re.split(r"[,•|;]", raw_skills) if s.strip()
            ]

    # 5. If first_name / last_name still not set but full_name is, split it
    if profile.full_name and not profile.first_name:
        parts = profile.full_name.split()
        if parts:
            profile.first_name = parts[0]
            profile.last_name = parts[-1] if len(parts) > 1 else None

    return profile
