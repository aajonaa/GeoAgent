[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$BacklogArgs)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$cli = Join-Path $env:LOCALAPPDATA 'GeoAgent\backlog-md\1.53.0\node_modules\backlog.md\cli.js'
if (-not (Test-Path -LiteralPath $cli)) {
    throw 'Install backlog.md@1.53.0 in %LOCALAPPDATA%\GeoAgent\backlog-md\1.53.0 first. See the project guide.'
}
$node = (Get-Command node -ErrorAction Stop).Source
Push-Location -LiteralPath $root
try {
    & $node $cli @BacklogArgs
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code