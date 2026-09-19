"""Pre-commit privacy scan. Exit 1 on any hard finding.

Hard findings: personal e-mail addresses, secret-looking strings, Windows user paths,
local absolute paths, banned product/context words, tracked files that must not exist
(.env, logs, audio), and any term from an optional local extra-terms file
(never committed; path in EXTRA_TERMS_ENV). Review counts for words that are legitimate
in code but must not carry real data (transcript / log / token).

Banned literals are assembled from pieces or code points so that this file does not
match its own patterns.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRA_TERMS_ENV = "PRIVACY_SCAN_EXTRA_TERMS"
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".html", ".js", ".css", ".ps1",
                 ".yml", ".yaml", ".cfg", ".ini", ".example"}


def _chars(*code_points: int) -> str:
    return "".join(chr(c) for c in code_points)


_USERPROFILE = "USER" + "PROFILE"
_MENSETSU = _chars(0x9762, 0x63A5)                 # banned Japanese product-context word
_JITSU_ONSEI = _chars(0x5B9F, 0x97F3, 0x58F0)      # Japanese phrase for recorded human audio
_OLD_PRODUCT = "re" + "cue"
_OLD_CONTEXT = "inter" + "view"

HARD_PATTERNS = {
    "gmail / personal mail": re.compile(
        r"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)(?!example\.(?:com|invalid))[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "secret-looking token": re.compile(
        r"\b(?:sk-[A-Za-z0-9]{16,}|gh[pous]_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
        r"|ts_[A-Za-z0-9]{24,}|AKIA[0-9A-Z]{16})"),
    "api key assignment with value": re.compile(
        r"(?i)\b(TYPESAFE_API_KEY|OPENAI_API_KEY|API_KEY|SECRET_KEY|ACCESS_TOKEN)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    "windows user path": re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s\"']+", re.I),
    "local absolute path": re.compile(r"(?<![A-Za-z])[A-Za-z]:\\+dev\\", re.I),
    "unix home path": re.compile(r"/(?:c|mnt/c)/Users/[^/\s]+", re.I),
    "userprofile variable": re.compile("%" + _USERPROFILE + "%|[$]env:" + _USERPROFILE),
    "old product context": re.compile(
        r"(?i)\b" + _OLD_PRODUCT + r"\b|\b" + _OLD_CONTEXT + r"[-_ ]?assist\b|\b" + _OLD_CONTEXT + r"\b|" + _MENSETSU),
    "recorded human audio reference": re.compile(_JITSU_ONSEI + "|real[-_ ]" + "audio"),
}
REVIEW_WORDS = ("transcript", "log", "token")
FORBIDDEN_TRACKED = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)logs/"),
    re.compile(r"\.(wav|flac|mp3|ogg|log)$", re.I),
)


def tracked_or_pending_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def load_extra_terms() -> list[str]:
    path = os.environ.get(EXTRA_TERMS_ENV)
    if not path or not Path(path).is_file():
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [t.strip() for t in lines if t.strip() and not t.startswith("#")]


def main() -> int:
    files = tracked_or_pending_files()
    extra_terms = load_extra_terms()
    hard: list[str] = []
    review: dict[str, int] = {}
    for rel in files:
        for forbidden in FORBIDDEN_TRACKED:
            if forbidden.search(rel):
                hard.append(f"{rel}: forbidden file type in the index")
        path = ROOT / rel
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for name, pattern in HARD_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hard.append(f"{rel}:{line}: {name}: {match.group()[:60]}")
        low = text.lower()
        for term in extra_terms:
            index = low.find(term.lower())
            if index >= 0:
                line_no = text.count("\n", 0, index) + 1
                line_text = text.splitlines()[line_no - 1].strip()
                # Report our own line, never the private term itself.
                hard.append(f"{rel}:{line_no}: local extra term matched on line: {line_text[:80]}")
        for word in REVIEW_WORDS:
            count = len(re.findall(r"(?i)\b" + word + r"s?\b", text))
            if count:
                review[f"{rel}:{word}"] = count
    print(f"scanned {len(files)} files; extra terms: {len(extra_terms)}")
    if review:
        print("review counts (legitimate in code; make sure no real data is attached):")
        for key, count in sorted(review.items()):
            print(f"  {key} x{count}")
    if hard:
        print("HARD FINDINGS:")
        for item in hard:
            print("  " + item)
        return 1
    print("privacy scan OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
