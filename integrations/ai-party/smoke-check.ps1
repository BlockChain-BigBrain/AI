param(
  [string]$AiUrl = $(if ($env:TRACK_AI_URL) { $env:TRACK_AI_URL } else { 'http://127.0.0.1:8000' }),
  [string]$BackendUrl = $(if ($env:BACKEND_URL) { $env:BACKEND_URL } else { 'http://127.0.0.1:3000' })
)
$ErrorActionPreference = 'Stop'
function Check-Health([string]$name,[string]$url) {
  $r = Invoke-RestMethod -Uri "$url/health" -Method Get -TimeoutSec 10
  if ($null -eq $r) { throw "$name returned an empty health response" }
  Write-Host "$name health: OK"
}
Check-Health 'AI' $AiUrl
Check-Health 'Backend' $BackendUrl
$contract = Get-Content (Join-Path $PSScriptRoot 'contract.json') -Raw | ConvertFrom-Json
if ($contract.ai.submit -ne 'POST /verify' -or $contract.ai.poll -ne 'GET /verify/{jobId}') { throw 'AI contract mismatch' }
if ($contract.ai.decisions.Count -ne 4) { throw 'Decision contract mismatch' }
Write-Host 'AI Party contract: OK'
