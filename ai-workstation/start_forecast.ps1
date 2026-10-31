$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
$service = Join-Path $root 'forecast_service.py'
$log = Join-Path $root 'forecast-service.log'
if (-not (Test-Path $python)) { throw 'Install Python virtual environment first' }
"[$(Get-Date -Format o)] Starting read-only forecast service" | Out-File -FilePath $log -Append
& $python -u $service *>> $log
