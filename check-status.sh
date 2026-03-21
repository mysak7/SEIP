#!/bin/bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIRTY=0

check_repo() {
    local path="$1"
    local name="$(basename "$path")"

    if [ ! -d "$path/.git" ]; then
        return
    fi

    local status
    status=$(git -C "$path" status --porcelain 2>/dev/null)

    local behind_ahead
    behind_ahead=$(git -C "$path" rev-list --left-right --count HEAD...@{u} 2>/dev/null)

    local has_issue=0
    local messages=()

    if [ -n "$status" ]; then
        has_issue=1
        messages+=("  uncommitted changes:")
        while IFS= read -r line; do
            messages+=("    $line")
        done <<< "$status"
    fi

    if [ -n "$behind_ahead" ]; then
        local behind ahead
        read -r behind ahead <<< "$behind_ahead"
        if [ "$ahead" -gt 0 ] 2>/dev/null; then
            has_issue=1
            messages+=("  unpushed commits: $ahead commit(s) ahead of remote")
        fi
        if [ "$behind" -gt 0 ] 2>/dev/null; then
            has_issue=1
            messages+=("  behind remote: $behind commit(s)")
        fi
    fi

    if [ "$has_issue" -eq 1 ]; then
        echo "[$name]"
        for msg in "${messages[@]}"; do
            echo "$msg"
        done
        echo ""
        DIRTY=1
    fi
}

echo "=== SEIP Status Check ==="
echo ""

# Check root repo itself
check_repo "$ROOT_DIR"

# Check all submodules
for dir in "$ROOT_DIR"/seip-*/; do
    check_repo "$dir"
done

if [ "$DIRTY" -eq 0 ]; then
    echo "All repos are clean."
fi
