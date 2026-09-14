"""Terminal-safe rendering of untrusted text shared by toolbox utilities."""

import re
import sys
import unicodedata


def safe_text(text):
    """Prevent external data from injecting terminal control sequences."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(text))
    return "".join(" " if ch in "\n\t" else ch for ch in text
                   if not unicodedata.category(ch).startswith("C") or ch in "\n\t")


def warn(message):
    print(f"Warning: {message}", file=sys.stderr)
