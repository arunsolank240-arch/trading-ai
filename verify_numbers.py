#!/usr/bin/env python3
"""Strict Anti-Hallucination Number Guard (verify_numbers.py).
Rule:
  - Numbers come ONLY from the Python scripts' JSON outputs (scanner, entry, exit, budget, risk, timemachine),
    NEVER invented by Gemini.
  - This script extracts every number appearing in a text brief (prices, percentages, quantities, charges, times, dates)
    and checks that every single number exists in the source JSON (`facts_json`).
  - If any number is not in the JSON, it flags `HALLUCINATION_DETECTED` with the exact offending number(s).

CLI Usage:
  python3 verify_numbers.py --brief trader/state/last_brief.txt --json trader/state/last_facts.json
"""
import argparse
import json
import math
import re
import sys


def _collect_json_numbers(obj, allowed_floats: set, allowed_strs: set):
    """Recursively collects all numeric values and numeric tokens from JSON objects/strings."""
    if obj is None or isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        val = float(obj)
        if math.isfinite(val):
            for nd in (0, 1, 2, 3, 4):
                r = round(val, nd)
                allowed_floats.add(r)
                allowed_floats.add(abs(r))
            allowed_strs.add(str(int(round(val))))
            allowed_strs.add(f"{val:.1f}")
            allowed_strs.add(f"{val:.2f}")
            allowed_strs.add(f"{abs(val):.1f}")
            allowed_strs.add(f"{abs(val):.2f}")
        return
    if isinstance(obj, str):
        # Extract any numeric tokens embedded in JSON strings (such as dates "2026-10-19", times "09:35", "15m", "1:2", "2R")
        for m in re.finditer(r"(?<![A-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?", obj):
            raw = m.group(0).replace(",", "")
            try:
                v = float(raw)
                for nd in (0, 1, 2):
                    allowed_floats.add(round(v, nd))
                    allowed_floats.add(abs(round(v, nd)))
                allowed_strs.add(raw.lstrip("+-"))
            except ValueError:
                pass
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _collect_json_numbers(k, allowed_floats, allowed_strs)
            _collect_json_numbers(v, allowed_floats, allowed_strs)
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_json_numbers(item, allowed_floats, allowed_strs)


def extract_brief_numbers(text: str) -> list:
    """Extracts all standalone or currency/percent/time numbers from a brief while ignoring ticker names and bullet list indices."""
    # Remove markdown bold/code markers first so *1401.40* or `1401.40` parses cleanly
    cleaned = re.sub(r"[*_`~]", " ", text)
    # Strip numbered list prefixes like "1. ", "• 1. ", "2. " at start of lines/bullets
    cleaned = re.sub(r"(?:^|\n)\s*(?:[•\-]\s*)?\d+\.\s+", "\n", cleaned)
    found = []
    # Match numbers (with optional commas and decimals) not glued inside uppercase ticker words
    pattern = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
    for m in pattern.finditer(cleaned):
        token = m.group(0)
        norm = token.replace(",", "").lstrip("+-")
        try:
            val = float(norm)
            found.append((token, norm, val))
        except ValueError:
            continue
    return found


def verify_brief_numbers(brief_text: str, source_json_data, tolerance: float = 0.015) -> dict:
    """Checks that every number in `brief_text` comes from `source_json_data`.
    Returns:
      {
        "ok": True/False,
        "total_numbers_checked": int,
        "hallucinated_numbers": [str, ...],
        "verified_numbers": [str, ...]
      }
    """
    allowed_floats = set()
    allowed_strs = set()
    _collect_json_numbers(source_json_data, allowed_floats, allowed_strs)

    extracted = extract_brief_numbers(brief_text)
    hallucinated = []
    verified = []

    for raw_tok, norm_str, val in extracted:
        aval = abs(val)
        if norm_str in allowed_strs or round(val, 2) in allowed_floats or round(aval, 2) in allowed_floats:
            verified.append(raw_tok)
            continue
        # Check within small rounding tolerance (e.g. 0.01 rupee/percent rounding from JSON floats)
        matched = False
        for af in allowed_floats:
            if abs(aval - af) <= tolerance:
                matched = True
                break
        if matched:
            verified.append(raw_tok)
        else:
            hallucinated.append(raw_tok)

    return {
        "ok": len(hallucinated) == 0,
        "total_numbers_checked": len(extracted),
        "hallucinated_numbers": hallucinated,
        "verified_numbers": verified,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Verify that every number in a Gemini/bot brief exists in the source JSON.")
    ap.add_argument("--brief", required=True, help="Path to text brief file")
    ap.add_argument("--json", required=True, nargs="+", help="One or more source JSON files")
    args = ap.parse_args()

    with open(args.brief, encoding="utf-8") as f:
        brief_txt = f.read()

    combined_json = []
    for jp in args.json:
        with open(jp, encoding="utf-8") as f:
            combined_json.append(json.load(f))

    res = verify_brief_numbers(brief_txt, combined_json)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if not res["ok"]:
        print(f"ERROR: Hallucinated numbers detected not in JSON: {res['hallucinated_numbers']}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: All {res['total_numbers_checked']} numbers in brief verified against JSON.")
