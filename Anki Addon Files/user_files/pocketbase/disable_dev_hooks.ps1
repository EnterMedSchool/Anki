$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$addonRoot = Split-Path -Parent $here

$hooksDir = Join-Path $addonRoot 'pocketbase\pb_hooks'
$destHook = Join-Path $hooksDir 'sync_terms.pb.js'
if (Test-Path $destHook) { Remove-Item -Force $destHook }

# Remove dev menu flag
$flagPath = Join-Path $here 'dev.flag'
if (Test-Path $flagPath) { Remove-Item -Force $flagPath }

Write-Host "Dev hooks disabled. Restart PocketBase (and Anki) to apply."

