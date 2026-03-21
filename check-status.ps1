# check-status.ps1 – PowerShell equivalent of check-status.sh
# Checks git status for the root SEIP repo and all seip-* subdirectories.

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dirty = $false

function Check-Repo {
    param([string]$path)

    if (-not (Test-Path "$path\.git")) { return }

    $name = Split-Path -Leaf $path

    # Pull latest from remote
    Write-Host "  Pulling $name..."
    git -C $path pull --ff-only 2>&1 | ForEach-Object { Write-Host "    $_" }
    Write-Host ""

    $status      = git -C $path status --porcelain 2>$null
    $behindAhead = git -C $path rev-list --left-right --count "HEAD...@{u}" 2>$null

    $hasIssue = $false
    $messages = @()

    if ($status) {
        $hasIssue = $true
        $messages += "  uncommitted changes:"
        $status -split "`n" | ForEach-Object {
            if ($_ -ne "") { $messages += "    $_" }
        }
    }

    if ($behindAhead) {
        $parts  = $behindAhead -split '\s+'
        $behind = [int]$parts[0]
        $ahead  = [int]$parts[1]

        if ($ahead -gt 0) {
            $hasIssue = $true
            $messages += "  unpushed commits: $ahead commit(s) ahead of remote"
        }
        if ($behind -gt 0) {
            $hasIssue = $true
            $messages += "  behind remote: $behind commit(s)"
        }
    }

    if ($hasIssue) {
        Write-Host "[$name]"
        $messages | ForEach-Object { Write-Host $_ }
        Write-Host ""
        $script:dirty = $true
    }
}

Write-Host "=== SEIP Status Check ==="
Write-Host ""

# Check root repo itself
Check-Repo $rootDir

# Check all seip-* subdirectories
Get-ChildItem -Path $rootDir -Directory -Filter "seip-*" | ForEach-Object {
    Check-Repo $_.FullName
}

if (-not $dirty) {
    Write-Host "All repos are clean."
}
