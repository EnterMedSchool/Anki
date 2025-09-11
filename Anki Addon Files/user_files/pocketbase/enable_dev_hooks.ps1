$ErrorActionPreference = 'Stop'

# Compute addon root from this script path
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$addonRoot = Split-Path -Parent $here  # user_files -> addon root

$devHook = Join-Path $addonRoot 'pocketbase\pb_hooks_dev\sync_terms_dev.pb.js'
$hooksDir = Join-Path $addonRoot 'pocketbase\pb_hooks'
$destHook = Join-Path $hooksDir 'sync_terms.pb.js'

if (-not (Test-Path $devHook)) {
  Write-Error "Dev hook not found: $devHook"
}

New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
Copy-Item -Force $devHook $destHook

# Create a local flag to show dev menu in Anki
$flagDir = Join-Path $here '.'
New-Item -ItemType Directory -Force -Path $flagDir | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $flagDir 'dev.flag') | Out-Null

Write-Host "Dev hooks enabled. Restart PocketBase (and Anki) to apply."

