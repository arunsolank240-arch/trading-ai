#!/usr/bin/env python3
"""Clean wrapper around brief.py (`ai_agent.py`)."""
from brief import (
    generate_morning_brief as format_premarket_with_ai,
    generate_setup_brief as format_intraday_setup_with_ai,
    generate_evening_review_brief as format_eod_report_with_ai,
)
