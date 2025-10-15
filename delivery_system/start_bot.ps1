$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $HERE
$envFile = Join-Path $HERE '.env'
if (Test-Path $envFile) {
  Get-Content -Path $envFile | Where-Object { $_ -match '=' } | ForEach-Object {
    $kv = $_ -split '=',2
    [Environment]::SetEnvironmentVariable($kv[0], $kv[1])
  }
}
if (-not $env:BOT_TOKEN) {
  Write-Error "BOT_TOKEN não definido. Crie um .env com BOT_TOKEN=..."
  exit 1
}

# Preferir venv local da pasta
$localVenvPy = Join-Path $HERE '..\.venv\Scripts\python.exe'
if (Test-Path $localVenvPy) {
  & $localVenvPy "bot.py"
} else {
  & "$env:USERPROFILE/.venv/Scripts/python.exe" "bot.py"
}
