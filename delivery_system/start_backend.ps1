param(
  [int]$Port = 8001
)
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $HERE
# Carrega .env (se existir)
Get-Content -Path (Join-Path $HERE '.env') -ErrorAction SilentlyContinue |
  Where-Object { $_ -match '=' } |
  ForEach-Object {
    $kv = $_ -split '=',2
    [Environment]::SetEnvironmentVariable($kv[0], $kv[1])
  }

# Preferir venv local da pasta do workspace, com fallback para %USERPROFILE%\.venv
$localVenvPy = Join-Path $HERE '..\.venv\Scripts\python.exe'
if (Test-Path $localVenvPy) {
  & $localVenvPy -m uvicorn app:app --host 0.0.0.0 --port $Port
} else {
  & "$env:USERPROFILE/.venv/Scripts/python.exe" -m uvicorn app:app --host 0.0.0.0 --port $Port
}
