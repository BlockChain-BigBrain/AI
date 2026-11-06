[CmdletBinding()]
param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $python) { throw 'Python을 찾지 못했습니다.' }
if (-not $cloudflared) { throw 'cloudflared를 찾지 못했습니다. 먼저 cloudflared를 설치하세요.' }

$token = [Convert]::ToHexString((1..32 | ForEach-Object { Get-Random -Maximum 256 })).ToLowerInvariant()
$log = Join-Path $env:TEMP ("track-ai-cloudflared-{0}.log" -f ([guid]::NewGuid().ToString('N')))
$serverInfo = New-Object System.Diagnostics.ProcessStartInfo
$serverInfo.FileName = $python
$serverInfo.WorkingDirectory = $repoRoot
$serverInfo.UseShellExecute = $false
$serverInfo.CreateNoWindow = $true
$serverInfo.ArgumentList.Add('api\server.py')
$serverInfo.Environment['TRACK_AI_HOST'] = '127.0.0.1'
$serverInfo.Environment['TRACK_AI_PORT'] = [string]$Port
$serverInfo.Environment['TRACK_AI_API_TOKEN'] = $token
$server = [System.Diagnostics.Process]::Start($serverInfo)

try {
  Start-Sleep -Seconds 3
  $tunnelInfo = New-Object System.Diagnostics.ProcessStartInfo
  $tunnelInfo.FileName = $cloudflared
  $tunnelInfo.WorkingDirectory = $repoRoot
  $tunnelInfo.UseShellExecute = $false
  $tunnelInfo.CreateNoWindow = $true
  $tunnelInfo.RedirectStandardOutput = $true
  $tunnelInfo.RedirectStandardError = $true
  $tunnelInfo.ArgumentList.Add('tunnel')
  $tunnelInfo.ArgumentList.Add('--url')
  $tunnelInfo.ArgumentList.Add("http://127.0.0.1:$Port")
  $tunnel = [System.Diagnostics.Process]::Start($tunnelInfo)
  $tunnel.BeginOutputReadLine(); $tunnel.BeginErrorReadLine()
  $tunnel.add_OutputDataReceived({ param($s,$e) if ($e.Data) { Add-Content -LiteralPath $log -Value $e.Data } })
  $tunnel.add_ErrorDataReceived({ param($s,$e) if ($e.Data) { Add-Content -LiteralPath $log -Value $e.Data } })

  $publicUrl = $null
  for ($i = 0; $i -lt 60 -and -not $publicUrl; $i++) {
    Start-Sleep -Seconds 1
    $text = Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue
    $m = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Success) { $publicUrl = $m.Value }
  }
  if (-not $publicUrl) { throw "Cloudflare Tunnel URL을 받지 못했습니다. 로그: $log" }

  Write-Host ''
  Write-Host 'AI_PROVIDER_MODE=http'
  Write-Host ("AI_API_URL={0}" -f $publicUrl)
  Write-Host ("TRACK_AI_API_KEY={0}" -f $token)
  Write-Host ''
  Write-Host '위 3줄을 백엔드 PC의 .env에 입력하세요.' -ForegroundColor Yellow
  Write-Host '이 창을 닫으면 AI 서버와 Tunnel이 종료됩니다.' -ForegroundColor Yellow
  while (-not $server.HasExited -and -not $tunnel.HasExited) { Start-Sleep -Seconds 2 }
} finally {
  if ($tunnel -and -not $tunnel.HasExited) { $tunnel.Kill($true) }
  if ($server -and -not $server.HasExited) { $server.Kill($true) }
  Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
}
