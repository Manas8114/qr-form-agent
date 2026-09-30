<div align="center">
  <h1>🎯 qr-form-agent</h1>
  <p><b>A human-in-the-loop agent for secure, automated job applications from real-world QR codes.</b></p>
</div>

---

**qr-form-agent** is a robust, security-first automation tool designed for career fairs and networking events. It extracts verified profile data from your resume, detects and decodes multiple QR codes from photos of job boards, validates URLs, and securely pre-fills complex Applicant Tracking System (ATS) forms using deterministic rules and isolated LLM fallbacks.

Most importantly, it operates under **strict human-in-the-loop invariants**: it physically cannot submit an application without your explicit approval and a cryptographic hash match of the form's state.

## ✨ Key Features

- 📸 **Bulk QR & Label OCR:** Scan photos of entire career fair boards. Decodes QRs and reads the surrounding printed text (company, role, deadline) to provide immediate context.
- 🚦 **Intelligent Triage:** Before touching a form, the agent classifies the destination as `FORM`, `LANDING_PAGE`, `LOGIN_WALL`, `CLOSED`, or `DEAD`.
- 🚀 **1-Hop Apply Navigation:** Automatically finds and clicks "Apply Now" buttons on landing pages to reach the actual ATS form.
- 🧠 **Smart Mapping Engine:** Tiered mapping using specialized adapters (Workday, Greenhouse, Lever, CoreHR), a Saved Answers Bank, and a zero-tool isolated LLM for edge cases.
- 📝 **Per-Job Tailoring:** Automatically tailors your resume and cover letter drafts for specific roles, guarded by a strict no-fabrication checker.
- 📊 **Tracker & Dashboard:** Built-in mobile-friendly review dashboard (`localhost:8000`) for one-click approvals, plus CSV/Notion/iCal export for application tracking.

## 🔒 Security Invariants & Hard Requirements

This agent was built because traditional web automation is too risky for sensitive PII. 

1. **Submission Impossible Without Approval:**
   - **Capture-Phase Lock:** Injects initialization scripts to intercept `'submit'` events (`preventDefault`).
   - **Route Quarantine:** The `FillRouteGuard` aborts all mutating (POST/PUT/DELETE) requests to form action endpoints during the fill phase.
   - **Cryptographic Snapshot:** The submitter accepts *only* jobs in the `APPROVED` state and verifies that the live DOM values match an approved SHA-256 snapshot hash before submission.
2. **Untrusted Web Content & Zero-Tool LLM:**
   - The field-mapping LLM has **no tools**, receives only metadata and the verified profile, and outputs strict JSON. Unmapped fields remain `null`.
3. **Fail-Closed Denylist:**
   - Passwords, OTPs, CAPTCHAs, banking info, and government IDs (SSN) automatically fail-closed and transition the job to `NEEDS_HUMAN`.
4. **URL Safety Gate & SSRF Protection:**
   - Strict `https://` enforcement. DNS resolution blocks private, loopback, and link-local IP addresses to prevent Server-Side Request Forgery (SSRF). Redirect chains are verified hop-by-hop.

---

## 🛠️ Real-World Resilience

The agent is heavily optimized for modern, heavily-obfuscated ATS platforms:
- **Shadow DOM Piercing:** Recursively walks shadow roots to find inputs hidden by Workday and Lever.
- **SPA Hydration Wait:** Intelligently waits for network idle states and sentinel elements to ensure React/Angular forms are fully rendered before extraction.
- **Non-blocking XHR:** Route guards selectively block final submissions while allowing the SPA's own XHR requests to pass (ensuring conditional fields and dropdowns work normally).

---

## 🚀 Getting Started

### 1. Installation

Requires Python 3.9+ and Node.js (for Playwright).

```bash
# Clone the repository
git clone https://github.com/Manas8114/qr-form-agent.git
cd qr-form-agent

# Install package and dependencies in editable mode
pip install -e .

# Install Playwright browser binaries
python -m playwright install chromium
```

### 2. Configuration

Copy the example environment file and fill in your LLM API keys (OpenAI/Anthropic) and optional Telegram credentials:

```bash
cp .env.example .env
```

---

## 💻 Usage Guide

### Step 1: Parse and Verify Resume Profile

Parse your resume once and save it to local verified storage:

```bash
qr-form-agent extract-profile --resume path/to/resume.pdf
```

### Step 2: One-Command Full Flow (Run)

Execute the end-to-end pipeline on a photo of a job board:

```bash
# Run full flow on a photo:
qr-form-agent run board.jpg

# Dry-run audit report mode (shows what would be filled vs refused):
qr-form-agent run board.jpg --dry-run

# Batch re-scan mode (processes only newly discovered codes on updated boards):
qr-form-agent run board.jpg --diff-only
```

### Step 3: Human Review Dashboard

Start the local review server to approve staged pre-fills:

```bash
qr-form-agent review
```
Navigate to `http://localhost:8000` (desktop or mobile) to view live screenshots, side-by-side field comparisons, and confidence indicators. Click **Approve** to stage the job for final submission.

### Step 4: Submit Approved Job

Once approved in the dashboard, trigger the final submission:

```bash
qr-form-agent submit --job-id <JOB_UUID>
```

### Step 5: Application Tracking & Exports

Track application statuses, export data, and manage custom answers:

```bash
# List all tracked applications:
qr-form-agent tracker

# Export applications to CSV or Notion:
qr-form-agent tracker --export-csv applications.csv
qr-form-agent tracker --export-notion notion_applications.csv

# Export deadlines to iCalendar:
qr-form-agent tracker --export-ics reminders.ics

# Manage the Saved Answers Bank:
qr-form-agent answers-bank
```

### 🛑 Global Kill Switch

Immediately freeze the entire agent across all workers in case of an emergency:

```bash
qr-form-agent kill-switch activate
qr-form-agent kill-switch status
qr-form-agent kill-switch deactivate
```

---

## 📂 Architecture

<details>
<summary>Click to expand project structure</summary>

```text
qr-form-agent/
├── qr_form_agent/
│   ├── config.py             # Settings management
│   ├── cli.py                # Unified CLI entry point
│   ├── pipeline.py           # End-to-end pipeline orchestrator
│   ├── core/                 # DB, state machine, rate limiter, kill switch
│   ├── profile/              # Resume extraction & verified schema
│   ├── qr/                   # zxing-cpp multi-QR detection & OCR
│   ├── safety/               # SSRF gates, URL validation, deduplication
│   ├── browser/              # Playwright isolated contexts & Shadow DOM extractor
│   ├── mapping/              # Multi-tier mapping (Rules -> Bank -> LLM) & Denylist
│   ├── fill/                 # Safe DOM populator & Route Guards
│   ├── review/               # FastAPI dashboard & UI
│   ├── submit/               # Cryptographic snapshot verifier & final submitter
│   ├── triage/               # Page classifiers & landing page hopper
│   └── adapters/             # Specialized mapping (Workday, Greenhouse, etc.)
└── tests/                    # 75+ tests & real-world HTML fixtures
```
</details>

---

## 🧪 Testing

The project maintains a rigorous test suite (75+ passing tests) utilizing realistic HTML fixtures for various ATS platforms to ensure security invariants are never breached.

```bash
pytest -v
```

---

## 📜 License

MIT License. See `LICENSE` for details.
