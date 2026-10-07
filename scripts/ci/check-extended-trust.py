#!/usr/bin/env python3
"""Fail closed if the reviewed immutable callee or caller changes."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = "b2de1048d97b65b8257a179173544af9b2758d202f6b02bfa473fe1a17dba11a"
PIN = "43df5b1f34bcd08d78a5dce4684c8b0a83aee212"

def validate(root):
    source = root / ".github/workflows/extended-trusted.yml"
    if hashlib.sha256(source.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError("Immutable extended callee changed: renew source and policy review")
    caller = (root / ".github/workflows/extended-validation.yml").read_text()
    if caller.count("uses:") != 1 or f"extended-trusted.yml@{PIN}" not in caller:
        raise ValueError("Caller must use the exact reviewed immutable source")
    for forbidden in ("runs-on:", "secrets:", "with:"):
        if forbidden in caller:
            raise ValueError("Caller cannot select runners, secrets or inputs")

if __name__ == "__main__":
    validate(ROOT)
    print("Extended immutable contract verified")
