#!/usr/bin/env bash
# install-git-hooks.sh — wire the repo's .githooks/ directory as git's
# hooks path so the CRLF pre-commit guard (and any future hooks) runs
# for every developer on every commit.
#
# Safe to re-run.  Idempotent.
#
# Usage:
#     bash deploy/hiclaw/install-git-hooks.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [[ ! -d .githooks ]]; then
    echo "ERROR: .githooks/ not found at $REPO_ROOT" >&2
    exit 1
fi

# Ensure every hook in .githooks/ is executable (esp. after fresh clone
# on Windows where Git may drop the +x bit).
chmod +x .githooks/* 2>/dev/null || true

# Point git at the versioned hooks directory.
git config core.hooksPath .githooks
echo "OK  git core.hooksPath = $(git config core.hooksPath)"

# Echo the list of active hooks for visibility.
echo "Active hooks:"
for f in .githooks/*; do
    [[ -f "$f" ]] || continue
    printf '  - %s\n' "$(basename "$f")"
done
