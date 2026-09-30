"""Browser automation package with anti-submit security locks, DOM extraction, and takeover."""

from qr_form_agent.browser.context import create_isolated_context
from qr_form_agent.browser.dom_extractor import (
    FormFieldDescriptor,
    FormExtractionResult,
    OptionDescriptor,
    extract_form_dom,
)
from qr_form_agent.browser.locks import ANTI_SUBMIT_INIT_SCRIPT
from qr_form_agent.browser.stepper import detect_multi_step_controls, launch_headful_takeover

__all__ = [
    "create_isolated_context",
    "FormFieldDescriptor",
    "FormExtractionResult",
    "OptionDescriptor",
    "extract_form_dom",
    "ANTI_SUBMIT_INIT_SCRIPT",
    "detect_multi_step_controls",
    "launch_headful_takeover",
]
