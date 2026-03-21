#!/usr/bin/env bash
# commit-all.sh — commit changes in every submodule, then update the parent repo
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMIT_MSG="${1:-chore: auto-commit changes}"

cd "$ROOT_DIR"

echo "==> Scanning submodules..."

git submodule foreach --quiet 'echo "$displaypath"' | while read -r sub; do
  sub_path="$ROOT_DIR/$sub"

  # Check for any changes (staged, unstaged, or untracked)
  if git -C "$sub_path" status --porcelain | grep -q .; then
    echo ""
    echo "--- [$sub] has changes ---"
    git -C "$sub_path" status --short

    git -C "$sub_path" add -A
    git -C "$sub_path" commit -m "$COMMIT_MSG"
    echo "    committed: $sub"
    git -C "$sub_path" push
    echo "    pushed: $sub"
  else
    echo "--- [$sub] clean, skipping ---"
  fi
done

echo ""
echo "==> Updating parent repo..."

# Stage submodule pointer changes + any root-level file changes
git add -A

if git diff --cached --quiet; then
  echo "    Parent repo: nothing to commit."
else
  git status --short
  git commit -m "$COMMIT_MSG"
  echo "    Parent repo committed."
fi

echo ""
echo "==> Pushing parent repo..."
git push
echo "Done."
