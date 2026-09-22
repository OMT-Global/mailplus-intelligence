#!/usr/bin/env python3
"""Fail closed if the reviewed immutable callee or caller changes."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = "cd6c14dc501e30baf674828975365957bda676da64fcdefe94d6d33216d2092b"
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
