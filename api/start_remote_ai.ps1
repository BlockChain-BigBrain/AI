[CmdletBinding()]
param(
  [int]$Port = 8000,
  [string]$Token = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw 'Python을 찾지 못했습니다. Python 3.11+ 설치 후 다시 실행하세요.' }

if ([string]::IsNullOrWhiteSpace($Token)) {
  $Token = [Convert]::ToHexString((1..32 | ForEach-Object { Get-Random -Maximum 256 })).ToLowerInvariant()
}

$lanIp = Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp -ErrorAction SilentlyContinue |
  Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } |
  Select-Object -First 1 -ExpandProperty IPAddress
if (-not $lanIp) { $lanIp = '<AI_PC_LAN_IP>' }

$env:TRACK_AI_HOST = '0.0.0.0'
$env:TRACK_AI_PORT = [string]$Port
$env:TRACK_AI_API_TOKEN = $Token

Write-Host ''
Write-Host '=== Track-AI remote AI connection values ===' -ForegroundColor Cyan
Write-Host '백엔드 PC의 .env에 아래 3줄을 입력하세요.' -ForegroundColor Yellow
Write-Host 'AI_PROVIDER_MODE=http'
Write-Host ("AI_API_URL=http://{0}:{1}" -f $lanIp, $Port)
Write-Host ("TRACK_AI_API_KEY={0}" -f $Token)
Write-Host ''
Write-Host 'AI 서버 주소: http://0.0.0.0:'$Port
Write-Host '이 PowerShell 창을 닫으면 AI 서버도 종료됩니다.' -ForegroundColor Yellow
Write-Host '=============================================' -ForegroundColor Cyan
Write-Host ''

Push-Location $repoRoot
try {
  & $python 'api\server.py'
} finally {
  Pop-Location
}
