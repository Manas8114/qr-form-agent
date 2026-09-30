"""Playwright security scripts and lock injection.

Enforces Hard Requirement 1:
1. Capture-phase 'submit' listener that unconditionally calls preventDefault() and stopImmediatePropagation().
2. Prototype override of HTMLFormElement.prototype.submit to throw an error.
3. Tracking counter of intercepted submission attempts for audit and verification.
"""

ANTI_SUBMIT_INIT_SCRIPT = """
(() => {
    // Flag to mark anti-submit shield active
    window.__QR_AGENT_SUBMIT_SHIELD_ACTIVE__ = true;
    window.__QR_AGENT_BLOCKED_SUBMITS__ = 0;

    // 1. Capture-phase event listener: fires before any page handlers
    window.addEventListener(
        'submit',
        function(event) {
            event.preventDefault();
            event.stopImmediatePropagation();
            window.__QR_AGENT_BLOCKED_SUBMITS__ = (window.__QR_AGENT_BLOCKED_SUBMITS__ || 0) + 1;
            console.warn('[QR_AGENT_LOCK] Form submission attempt blocked by capture-phase preventDefault()');
            return false;
        },
        true // Capture phase!
    );

    // 2. Override HTMLFormElement.prototype.submit to prevent script-driven form submissions
    try {
        const originalSubmit = HTMLFormElement.prototype.submit;
        HTMLFormElement.prototype.submit = function() {
            window.__QR_AGENT_BLOCKED_SUBMITS__ = (window.__QR_AGENT_BLOCKED_SUBMITS__ || 0) + 1;
            console.warn('[QR_AGENT_LOCK] Direct form.submit() call intercepted and blocked.');
            throw new Error('Form submission blocked by QR Form Agent security lock');
        };
    } catch (e) {
        console.error('Failed to override HTMLFormElement.prototype.submit:', e);
    }

    // 3. Override HTMLFormElement.prototype.requestSubmit
    try {
        if (HTMLFormElement.prototype.requestSubmit) {
            HTMLFormElement.prototype.requestSubmit = function() {
                window.__QR_AGENT_BLOCKED_SUBMITS__ = (window.__QR_AGENT_BLOCKED_SUBMITS__ || 0) + 1;
                console.warn('[QR_AGENT_LOCK] Direct form.requestSubmit() call intercepted and blocked.');
                throw new Error('Form requestSubmit blocked by QR Form Agent security lock');
            };
        }
    } catch (e) {
        console.error('Failed to override requestSubmit:', e);
    }
})();
"""
