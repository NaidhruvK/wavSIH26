"""Move Nehal's S4-S6 work into the cloned repo, without clobbering anyone.

    python docs/migrate_to_repo.py <path-to-clone>          # dry run, default
    python docs/migrate_to_repo.py <path-to-clone> --apply  # actually copy

Three days of work were built outside the repo because the repo did not exist
yet. Dropping it in with `cp -r` would overwrite four files that belong to
someone else or to everyone. So the file list is split deliberately:

  OWNED      my directories. Copied. Nobody else writes here, so there is
             nothing to lose.
  CONTESTED  files Naidhruv owns, or that we share a section of. Copied ONLY
             if absent from the clone. If present, the script reports the
             difference and touches nothing - reconciling those is a decision,
             not a file operation.

A dry run prints exactly what would happen and changes nothing.
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]

# Directories I own outright - see the Command Center ownership table.
OWNED_DIRS = [
    "pipeline/s4_recover",
    "pipeline/s5_decode",
    "pipeline/s6_frame",
    "tests/unit",
    "tests/fixtures",
    "reports",
]

OWNED_FILES = [
    "pipeline/__init__.py",
    "tests/__init__.py",
    "docs/zoo-bits-only-contract.md",
    "docs/python-version-decision.md",
    "docs/TEAM-SETUP.md",
    "docs/stack_check.py",
    "docs/stack_probe.txt",
    "docs/migrate_to_repo.py",
]

# Someone else's, or shared. Never overwritten.
CONTESTED = [
    ("requirements.txt",
     "Naidhruv committed his. Mine is pinned from a real 3.11.9 resolution and "
     "verified on Windows + python:3.11.9-slim. Diff them - if his lacks pins, "
     "or pins numpy>=2.5/scipy>=1.18 (which need Python 3.12), say so at the sync."),
    ("registry/__init__.py",
     "Naidhruv's folder. Mine is a strawman written only so S4 could satisfy "
     "'recovers through the registry'. If he has one, use HIS and I adapt my "
     "plug-ins to it."),
    ("registry/protocols.py",
     "Same. Only the three protocol shapes need to survive - the rest is his call."),
    (".gitignore",
     "Merge rather than replace. Mine adds .venv*/, .pytest_cache/, "
     "reports/*.log, docs/stack_*.log."),
    ("STATUS.md",
     "One section each. Paste my '## Nehal' section under his heading; do not "
     "copy the whole file over."),
]

SKIP_NAMES = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = {".log", ".pyc"}
# scratch output from the version investigation - not worth committing
SKIP_FILES = {"docs/freeze_311_full.txt"}


def iter_owned():
    for rel in OWNED_FILES:
        p = SRC / rel
        if p.is_file() and rel not in SKIP_FILES:
            yield rel
    for d in OWNED_DIRS:
        base = SRC / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if any(part in SKIP_NAMES for part in p.parts):
                continue
            if p.suffix in SKIP_SUFFIXES:
                continue
            rel = p.relative_to(SRC).as_posix()
            if rel not in SKIP_FILES:
                yield rel


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    dest = Path(argv[0]).expanduser().resolve()
    apply = "--apply" in argv

    if not (dest / ".git").is_dir():
        print("ERROR: %s is not a git clone (no .git). Clone the repo first."
              % dest, file=sys.stderr)
        return 2

    print("source : %s" % SRC)
    print("clone  : %s" % dest)
    print("mode   : %s" % ("APPLY" if apply else "dry run - nothing will change"))
    print()

    new = updated = same = 0
    for rel in iter_owned():
        s, d = SRC / rel, dest / rel
        if d.exists() and filecmp.cmp(s, d, shallow=False):
            same += 1
            continue
        tag = "update" if d.exists() else "new   "
        if d.exists():
            updated += 1
        else:
            new += 1
        print("  %s  %s" % (tag, rel))
        if apply:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)

    print()
    print("owned files: %d new, %d updated, %d already identical" % (new, updated, same))

    print()
    print("CONTESTED - decide these yourself, nothing above touched them")
    print("-" * 68)
    for rel, note in CONTESTED:
        s, d = SRC / rel, dest / rel
        if not s.exists():
            continue
        if not d.exists():
            print("  [absent in repo] %s" % rel)
            print("      safe to add. %s" % note)
            if apply:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
                print("      -> copied")
        elif filecmp.cmp(s, d, shallow=False):
            print("  [identical]      %s" % rel)
        else:
            print("  [DIFFERS]        %s   *** NOT TOUCHED ***" % rel)
            print("      %s" % note)
            print("      diff:  git diff --no-index \"%s\" \"%s\"" % (s, d))
        print()

    if not apply:
        print("Dry run only. Re-run with --apply once the list looks right.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
