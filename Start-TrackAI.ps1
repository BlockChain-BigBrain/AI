$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$nodePath = Join-Path $projectRoot '.tools/node/node.exe'
if (-not (Test-Path -LiteralPath $nodePath)) { $nodePath = (Get-Command node -ErrorAction Stop).Source }
$reportPath = Join-Path $projectRoot 'layer2/artifacts/ai_labeled_recalibration.json'
if (-not (Test-Path -LiteralPath $reportPath)) { throw 'Full evaluation is not complete. Check layer2/artifacts/mentoring_workflow_status.json.' }
$runtimePath = Join-Path $projectRoot '.runtime-tests/service-logs'
New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
$env:TRACK_AI_SCOPE = 'ai_labeled'
Start-Process -FilePath $pythonPath -ArgumentList @('api/server.py') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimePath 'api.log') -RedirectStandardError (Join-Path $runtimePath 'api-error.log')
Start-Process -FilePath $nodePath -ArgumentList @('--import','./backend/node_modules/tsx/dist/loader.mjs','backend/src/server.ts') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimePath 'backend.log') -RedirectStandardError (Join-Path $runtimePath 'backend-error.log')
Write-Output 'Track-AI is starting: http://127.0.0.1:3000/ (AI health: http://127.0.0.1:8000/health)'
