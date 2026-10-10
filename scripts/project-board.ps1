param([ValidateRange(1024, 65535)][int]$Port = 6420)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'backlog.ps1') browser --port "$Port" --no-open
exit $LASTEXITCODE