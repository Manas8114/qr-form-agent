"""Specialized ATS platform adapters module."""

from qr_form_agent.adapters.base import BaseATSAdapter
from qr_form_agent.adapters.corehr import CoreHRAdapter
from qr_form_agent.adapters.greenhouse import GreenhouseAdapter
from qr_form_agent.adapters.lever import LeverAdapter
from qr_form_agent.adapters.registry import AdapterRegistry
from qr_form_agent.adapters.workday import WorkdayAdapter

__all__ = [
    "BaseATSAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "WorkdayAdapter",
    "CoreHRAdapter",
    "AdapterRegistry",
]
