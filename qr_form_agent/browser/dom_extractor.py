"""Form DOM & accessibility tree extractor.

Extracts all interactive input fields, associated labels, types, requirements,
autocomplete hints, and select options while flagging denylisted security fields.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from playwright.sync_api import Frame, Page

logger = logging.getLogger(__name__)


class OptionDescriptor(BaseModel):
    value: str
    text: str


class FormFieldDescriptor(BaseModel):
    field_id: str = Field(description="Unique stable identifier for the field on this page")
    tag_name: str = Field(description="HTML tag name (input, textarea, select)")
    field_type: str = Field(default="text", description="Input type (text, email, tel, file, etc.)")
    name: Optional[str] = Field(default=None, description="HTML name attribute")
    id: Optional[str] = Field(default=None, description="HTML id attribute")
    label: str = Field(default="", description="Resolved human-readable label or aria-label")
    placeholder: Optional[str] = Field(default=None, description="Placeholder text")
    required: bool = Field(default=False, description="Whether field is required")
    autocomplete: Optional[str] = Field(default=None, description="HTML5 autocomplete attribute")
    options: List[OptionDescriptor] = Field(default_factory=list, description="Available options for select or radio groups")
    selector: str = Field(description="CSS or text selector to target this field")
    is_in_iframe: bool = Field(default=False, description="Whether this field resides in an iframe")
    current_value: Optional[str] = Field(default="", description="Current value populated in field")
    is_denylisted: bool = Field(default=False, description="Whether this field matches sensitive denylist categories")


class FormExtractionResult(BaseModel):
    url: str
    title: str
    fields: List[FormFieldDescriptor] = Field(default_factory=list)
    accessibility_tree: Optional[Dict[str, Any]] = None
    has_captcha: bool = False
    has_login_or_password: bool = False
    is_multi_step: bool = False


# JavaScript snippet executed in page to extract rich DOM metadata
EXTRACT_DOM_SCRIPT = """
(() => {
    const fields = [];
    const elements = Array.from(document.querySelectorAll('input, select, textarea'));

    function getLabelForElement(el) {
        // 1. Check aria-label
        if (el.getAttribute('aria-label')) {
            return el.getAttribute('aria-label').trim();
        }
        // 2. Check aria-labelledby
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const labelEl = document.getElementById(labelledBy);
            if (labelEl) return labelEl.innerText.trim();
        }
        // 3. Check label[for="id"]
        if (el.id) {
            const forLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (forLabel) return forLabel.innerText.trim();
        }
        // 4. Check ancestor label
        const parentLabel = el.closest('label');
        if (parentLabel) {
            // Clone and remove inputs to get text only
            const clone = parentLabel.cloneNode(true);
            clone.querySelectorAll('input, select, textarea').forEach(n => n.remove());
            const text = clone.innerText.trim();
            if (text) return text;
        }
        // 5. Immediately preceding sibling label
        const prev = el.previousElementSibling;
        if (prev && (prev.tagName.toLowerCase() === 'label' || prev.classList.contains('label'))) {
            return prev.innerText.trim();
        }
        // 6. Placeholder fallback
        if (el.placeholder) {
            return el.placeholder.trim();
        }
        // 7. Name or id fallback
        return el.name || el.id || '';
    }

    elements.forEach((el, index) => {
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || (tag === 'textarea' ? 'textarea' : 'text')).toLowerCase();

        // Skip buttons, submits, resets, and hidden fields
        if (['submit', 'button', 'reset', 'hidden', 'image'].includes(type)) {
            return;
        }

        // Generate robust selector
        let sel = '';
        if (el.id) {
            sel = `#${CSS.escape(el.id)}`;
        } else if (el.name) {
            sel = `${tag}[name="${CSS.escape(el.name)}"]`;
        } else {
            sel = `${tag}:nth-of-type(${index + 1})`;
        }

        const labelText = getLabelForElement(el);

        let optionsList = [];
        if (tag === 'select') {
            optionsList = Array.from(el.querySelectorAll('option')).map(opt => ({
                value: opt.value || opt.text,
                text: opt.text.trim()
            }));
        }

        fields.push({
            field_id: el.id || el.name || `field_${index}`,
            tag_name: tag,
            field_type: type,
            name: el.name || null,
            id: el.id || null,
            label: labelText,
            placeholder: el.placeholder || null,
            required: el.required || el.getAttribute('aria-required') === 'true',
            autocomplete: el.getAttribute('autocomplete') || null,
            options: optionsList,
            selector: sel,
            current_value: el.value || ''
        });
    });

    // Detect CAPTCHA indicators
    const hasCaptcha = !!document.querySelector(
        'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"], .g-recaptcha, .h-captcha, #cf-turnstile'
    );

    // Detect multi-step indicators
    const isMultiStep = !!document.querySelector(
        '.wizard, .step-indicator, .progress-bar, [data-step], .stepper, [aria-label*="Step"]'
    );

    return {
        fields: fields,
        has_captcha: hasCaptcha,
        is_multi_step: isMultiStep
    };
})();
"""


def extract_form_dom(page: Page) -> FormExtractionResult:
    """
    Extracts structured form field information, accessibility tree, and page metadata.
    """
    raw_res = page.evaluate(EXTRACT_DOM_SCRIPT)
    raw_fields = raw_res.get("fields", [])
    has_captcha = raw_res.get("has_captcha", False)
    is_multi_step = raw_res.get("is_multi_step", False)

    field_descriptors: List[FormFieldDescriptor] = []
    has_login_or_pw = False

    for item in raw_fields:
        f_type = item["field_type"].lower()
        f_name = (item["name"] or "").lower()
        f_id = (item["id"] or "").lower()
        f_label = (item["label"] or "").lower()

        # Check denylist tags
        is_denylisted = False
        if f_type in ("password",) or any(
            denied in f_name or denied in f_id or denied in f_label
            for denied in [
                "password", "passcode", "otp", "totp", "2fa", "two-factor",
                "ssn", "social security", "credit card", "cvv", "cvc", "cardnumber"
            ]
        ):
            is_denylisted = True
            if "password" in f_type or "password" in f_name:
                has_login_or_pw = True

        field_descriptors.append(
            FormFieldDescriptor(
                field_id=item["field_id"],
                tag_name=item["tag_name"],
                field_type=item["field_type"],
                name=item["name"],
                id=item["id"],
                label=item["label"],
                placeholder=item["placeholder"],
                required=item["required"],
                autocomplete=item["autocomplete"],
                options=[OptionDescriptor(**opt) for opt in item["options"]],
                selector=item["selector"],
                is_in_iframe=False,
                current_value=item["current_value"],
                is_denylisted=is_denylisted,
            )
        )

    # Optional accessibility snapshot
    try:
        a11y_tree = page.accessibility.snapshot()
    except Exception as e:
        logger.debug("Failed to extract accessibility snapshot: %s", e)
        a11y_tree = None

    return FormExtractionResult(
        url=page.url,
        title=page.title(),
        fields=field_descriptors,
        accessibility_tree=a11y_tree,
        has_captcha=has_captcha,
        has_login_or_password=has_login_or_pw,
        is_multi_step=is_multi_step,
    )
