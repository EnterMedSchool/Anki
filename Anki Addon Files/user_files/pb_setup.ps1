param(
  [string]$BaseUrl = "http://127.0.0.1:8090",
  [string]$AdminEmail,
  [string]$AdminPassword
)

$ProgressPreference = 'SilentlyContinue'

Write-Host "PocketBase setup script for Tamagotchi collection" -ForegroundColor Cyan
Write-Host "Base URL:" $BaseUrl

# Prompt for admin credentials if not supplied (local dev only)
if (-not $AdminEmail) { $AdminEmail = Read-Host "Admin email" }
if (-not $AdminPassword) { $AdminPassword = Read-Host "Admin password" }

function Invoke-PB {
  param([string]$Method, [string]$Url, $Body=$null, [string]$Token=$null)
  $headers = @{}
  if ($Token) { $headers["Authorization"] = "Bearer $Token" }
  if ($Body -ne $null -and ($Body -isnot [string])) { $Body = ($Body | ConvertTo-Json -Depth 10) }
  try {
    return Invoke-RestMethod -Method $Method -Uri $Url -Headers $headers -ContentType 'application/json' -Body $Body -TimeoutSec 20 -ErrorAction Stop
  } catch {
    $msg = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
    throw "${Method} ${Url} failed: ${msg}"
  }
}

try {
  # Preflight: public settings to verify base URL
  $settings = Invoke-PB -Method Get -Url ("{0}/api/settings" -f $BaseUrl)
  if (-not $settings) { throw "Couldn't reach ${BaseUrl}/api/settings (wrong BaseUrl or server not running?)" }
  Write-Host "API reachable (settings ok)" -ForegroundColor Green

  # Admin login (try email first, then identity)
  $loginUrl = ("{0}/api/admins/auth-with-password" -f $BaseUrl)
  $authResp = $null
  try {
    $authResp = Invoke-PB -Method Post -Url $loginUrl -Body @{ email=$AdminEmail; password=$AdminPassword }
  } catch {
    Write-Host "email login failed, trying identity field..." -ForegroundColor Yellow
    $authResp = Invoke-PB -Method Post -Url $loginUrl -Body @{ identity=$AdminEmail; password=$AdminPassword }
  }
  $token = $authResp.token
  if (-not $token) { throw "Admin login failed (no token)." }
  Write-Host "Admin login OK" -ForegroundColor Green

  # Check existing collection
  $colUrl = ("{0}/api/collections/tamagotchi" -f $BaseUrl)
  $exists = $false
  try {
    $cur = Invoke-PB -Method Get -Url $colUrl -Token $token
    if ($cur) { $exists = $true }
  } catch {
    $exists = $false
  }

  $payload = @{ 
    name = 'tamagotchi';
    type = 'base';
    schema = @(
      @{ name='user'; type='relation'; required=$true; unique=$false; options=@{ collectionId='_pb_users_auth_'; cascadeDelete=$true; minSelect=1; maxSelect=1 } },
      @{ name='data'; type='json'; required=$true; unique=$false; options=@{} }
    );
    listRule = "user = @request.auth.id";
    viewRule = "user = @request.auth.id";
    createRule = "@request.auth.id != '' && user = @request.auth.id";
    updateRule = "user = @request.auth.id";
    deleteRule = "user = @request.auth.id";
    indexes = @(
      "CREATE UNIQUE INDEX idx_tamagotchi_user ON tamagotchi (user)"
    )
  }

  if ($exists) {
    Write-Host "Collection 'tamagotchi' already exists. Updating rules/indexes/fields..." -ForegroundColor Yellow
    $res = Invoke-PB -Method Patch -Url $colUrl -Token $token -Body $payload
  } else {
    Write-Host "Creating collection 'tamagotchi'..." -ForegroundColor Yellow
    $res = Invoke-PB -Method Post -Url ("{0}/api/collections" -f $BaseUrl) -Token $token -Body $payload
  }

  # Verify
  $check = Invoke-PB -Method Get -Url $colUrl -Token $token
  if ($check -and $check.name -eq 'tamagotchi') {
    Write-Host "PocketBase collection 'tamagotchi' is ready." -ForegroundColor Green
  } else {
    throw "Verification failed: collection not found or wrong name."
  }

} catch {
  Write-Host ("Error: {0}" -f $_) -ForegroundColor Red
  exit 1
}

Write-Host "Done." -ForegroundColor Green
