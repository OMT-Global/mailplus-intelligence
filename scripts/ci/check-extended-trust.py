#!/usr/bin/env python3
"""Fail closed if the reviewed immutable callee or caller changes."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = "2b1827b501d3c7ce24440b40167491fd9d27f94ce24d9b378cf5890a9f07d44f"
PIN = "d08b5ee74df3eb6d016e9e4aa267acc4bcafd154"

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
