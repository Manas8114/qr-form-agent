# qr-form-agent

A human-in-the-loop agent that extracts verified profile data from a resume, detects & decodes multiple QR codes from an image, validates target URLs through an SSRF/security gate, inspects forms with Playwright under strict anti-submission sandbox locks, maps fields using deterministic rules + zero-tool LLM fallbacks, stages pre-fills, and requires explicit human review and cryptographic snapshot-hash verification before final submission.

---

## 🔒 Security Invariants & Hard Requirements

1. **Submission Impossible Without Human Approval:**
   - **Capture-Phase Lock:** Playwright injects an initialization script into all frames intercepting the `'submit'` event and calling `event.preventDefault()` and `event.stopImmediatePropagation()`.
   - **Route Quarantine:** During the fill phase, `FillRouteGuard` aborts all non-GET requests (`route.abort("blockedbyclient")`) to form action endpoints and external APIs.
   - **No Submit Primitives:** The `fill/` module strictly refuses to interact with or click buttons of type `submit`.
   - **Cryptographic Snapshot Check:** The `submit/` module accepts *only* jobs in the `APPROVED` state and re-verifies that the live DOM values match the approved SHA-256 snapshot hash before allowing submission.
2. **Untrusted Web Content & Zero-Tool LLM:**
   - Web pages are treated as untrusted. The field-mapping LLM call has **no tools**, receives only field metadata and the verified candidate profile, and outputs strictly JSON:
     `[{field_id, profile_key|null, value|null, confidence 0-1, reason}]`.
   - Values must originate from the profile; unmapped fields remain strictly `null`.
3. **Fail-Closed Denylist:**
   - Password, OTP, CAPTCHA, credit cards / banking, government IDs (SSN, Aadhaar), or any unmapped mandatory field fail closed and trigger the `NEEDS_HUMAN` state.
4. **URL Safety Gate:**
   - Strict `https://` enforcement.
   - DNS resolution blocks private, loopback, multicast, and link-local IP addresses (e.g. RFC 1918, RFC 3927, `169.254.169.254`).
   - Redirect chains are verified hop-by-hop.
   - Discovered URLs are presented to the operator for confirmation before opening.

---

## 📂 Project Architecture

```text
qr-form-agent/
├── qr_form_agent/
│   ├── config.py             # Settings management with pydantic-settings
│   ├── cli.py                # Unified CLI entry point
│   ├── pipeline.py           # End-to-end pipeline orchestrator
│   ├── core/
│   │   ├── state_machine.py  # SQLite-backed state machine (QUEUED -> ... -> SUBMITTED)
│   │   ├── db.py             # SQLite models, jobs & audit logging
│   │   ├── rate_limiter.py   # Per-domain sliding window rate limiter
│   │   └── kill_switch.py    # Global atomic kill switch
│   ├── profile/
│   │   ├── schema.py         # Nullable Pydantic Profile schema
│   │   ├── extractor.py      # PyMuPDF text parser + OCR fallback
│   │   ├── synthesizer.py    # Structured profile extraction via LLM
│   │   └── storage.py        # Local verified profile.json manager
│   ├── qr/
│   │   ├── decoder.py        # zxing-cpp multi-QR detection & deduplication
│   │   └── preprocessors.py  # Upscaling, adaptive thresholding, tiled crop scan
│   ├── safety/
│   │   ├── url_gate.py       # HTTPS check, DNS resolving, SSRF filter
│   │   ├── dedupe.py         # URL canonicalization & deduplication
│   │   └── gate.py           # Batch gate and operator confirmation prompt
│   ├── browser/
│   │   ├── context.py        # Isolated Playwright context factory
│   │   ├── dom_extractor.py  # Form DOM & accessibility tree extractor
│   │   ├── locks.py          # Anti-submit capture preventDefault() scripts
│   │   └── stepper.py        # Multi-step detection & headful takeover handler
│   ├── mapping/
│   │   ├── denylist.py       # Fail-closed denylist detector
│   │   ├── tier1_rules.py    # Autocomplete, input type, label regex heuristics
│   │   ├── tier2_llm.py      # Zero-tool isolated JSON LLM mapper
│   │   ├── engine.py         # Unified mapping engine
│   │   └── cache.py          # SQLite per-domain mapping cache
│   ├── fill/
│   │   ├── filler.py         # Safe DOM field populator (zero submit primitives)
│   │   ├── uploader.py       # Resume attachment handler (review-flagged only)
│   │   ├── route_guard.py    # Route interceptor aborting non-GET requests
│   │   └── snapshot.py       # Deterministic SHA-256 snapshot generator & screenshot
│   ├── review/
│   │   ├── app.py            # FastAPI review server & REST API
│   │   ├── notifications.py  # Optional Telegram review notifications
│   │   └── static/index.html # Modern dark-mode review dashboard
│   └── submit/
│       ├── submitter.py      # Isolated submitter requiring APPROVED state
│       ├── verifier.py       # Live DOM vs approved snapshot hash verifier
│       └── confirmation.py   # Post-submit screenshot and receipt capture
└── tests/
    ├── fixtures/forms/       # 15 HTML test fixtures covering realistic form patterns
    ├── test_qr.py            # QR detection, fallbacks, and deduplication tests
    ├── test_profile.py       # Profile extraction, null-fidelity, and schema tests
    ├── test_safety.py        # SSRF, private IPs, loopback, and redirect tests
    ├── test_browser_locks.py # Submit-block tests (proves submit cannot occur in fill phase)
    ├── test_mapping.py       # Mapping accuracy and denylist tests across fixtures
    ├── test_state_machine.py # State machine transitions and audit log tests
    └── test_submit.py        # Hash verification and isolated submission tests
```

---

## 🚀 Getting Started

### 1. Installation

```bash
# Clone the repository and navigate into it
cd qr-form-agent

# Install package and dependencies in editable mode
pip install -e .

# Install Playwright browser binaries
python -m playwright install chromium
```

### 2. Configuration

Copy `.env.example` to `.env` and fill in any optional LLM keys or Telegram credentials:

```bash
cp .env.example .env
```

### 3. Usage

#### Step 1: Parse and Verify Resume Profile

Parse your resume once and save to local verified storage:

```bash
qr-form-agent extract-profile --resume path/to/resume.pdf
```

#### Step 2: One-Command Full Flow (Run)

Execute the entire end-to-end pipeline with a single command:
- Reads printed labels & notices outside each QR code
- Diffs against previously seen URLs (batch re-scan)
- Pre-triages each destination (`FORM`, `LANDING_PAGE`, `LOGIN_WALL`, `CLOSED`, `DEAD`)
- Automatically traverses 1-hop "Apply" landing links through SSRF gate
- Maps fields using specialized ATS adapters (Workday, Greenhouse, Lever, CoreHR) & Saved Answers Bank
- Performs per-job resume & cover letter tailoring with no-fabrication validation
- Stages pre-fills and outputs a rich summary table

```bash
# Run full flow on photo of board:
qr-form-agent run board.jpg

# Dry-run audit report mode (shows every field that would be filled vs refused):
qr-form-agent run board.jpg --dry-run

# Batch re-scan mode (processes only newly discovered codes on updated boards):
qr-form-agent run board.jpg --diff-only
```

#### Step 3: Mobile-Friendly Human Review Dashboard & Control Center

Start the local review server:

```bash
qr-form-agent review
```

Navigate to `http://localhost:8000` (desktop or mobile):
- **Camera Upload:** Directly photograph or upload career boards from your phone camera (`capture="environment"`).
- **Side-by-Side Review:** Live screenshot alongside pre-filled values, source profile field, and confidence indicators. Low-confidence fields are sorted to the top.
- **Bulk Approve:** One-click approval for all high-confidence jobs.
- **"Continue Here" Handoff:** Launch headful browser takeover for CAPTCHAs or login walls and resume automatically.

#### Step 4: Submit Approved Job

Once a job is approved in the dashboard, trigger submission:

```bash
qr-form-agent submit --job-id <JOB_UUID>
```

#### Step 5: Application Tracker, Reminders & Exports

Track application statuses, deadlines, and opening notices with zero duplicates:

```bash
# List all tracked applications:
qr-form-agent tracker

# Export applications to CSV or Notion database CSV:
qr-form-agent tracker --export-csv applications.csv
qr-form-agent tracker --export-notion notion_applications.csv

# Export deadlines and opening reminders to iCalendar:
qr-form-agent tracker --export-ics reminders.ics

# View upcoming deadlines and opening notices:
qr-form-agent reminders

# View and manage the Saved Answers Bank:
qr-form-agent answers-bank
```

#### Global Kill Switch

To immediately freeze the entire agent across all workers:

```bash
qr-form-agent kill-switch activate
qr-form-agent kill-switch status
qr-form-agent kill-switch deactivate
```

---

## 🧪 Running the Test Suite

Run the full pytest suite (75 tests including Workday, Greenhouse, Lever, Google Forms, and security hardening):

```bash
pytest -v
```
