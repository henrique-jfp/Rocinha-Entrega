param(
  [int]$Port = 8001,
  [string]$NssmPath = 'C:\nssm\nssm.exe'
)

$ErrorActionPreference = 'Stop'
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $HERE

if (-not (Test-Path $NssmPath)) {
  $which = (Get-Command nssm.exe -ErrorAction SilentlyContinue)?.Source
  if ($which) { $NssmPath = $which }
}
if (-not (Test-Path $NssmPath)) {
  Write-Error "nssm.exe não encontrado. Baixe em https://nssm.cc/download e informe -NssmPath ou copie para C:\nssm\nssm.exe"
}

$logs = Join-Path $HERE 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$localVenvPy = Join-Path $HERE '..\.venv\Scripts\python.exe'
if (Test-Path $localVenvPy) {
  $python = $localVenvPy
} else {
  $python = Join-Path $env:USERPROFILE '.venv\Scripts\python.exe'
}
if (-not (Test-Path $python)) {
  Write-Error "Python do venv não encontrado em $python. Crie o venv e instale dependências antes."
}

# Backend service
& $NssmPath install EntregaBackend $python "-m uvicorn app:app --host 0.0.0.0 --port $Port"
& $NssmPath set EntregaBackend AppDirectory $HERE
& $NssmPath set EntregaBackend Start SERVICE_AUTO_START
& $NssmPath set EntregaBackend AppStdout (Join-Path $logs 'backend.out')
& $NssmPath set EntregaBackend AppStderr (Join-Path $logs 'backend.err')
& $NssmPath set EntregaBackend AppRotateFiles 1
& $NssmPath set EntregaBackend AppRotateOnline 1
& $NssmPath set EntregaBackend AppRotateSeconds 86400

# Bot service
& $NssmPath install EntregaBot $python "bot.py"
& $NssmPath set EntregaBot AppDirectory $HERE
& $NssmPath set EntregaBot Start SERVICE_AUTO_START
& $NssmPath set EntregaBot AppStdout (Join-Path $logs 'bot.out')
& $NssmPath set EntregaBot AppStderr (Join-Path $logs 'bot.err')
& $NssmPath set EntregaBot AppRotateFiles 1
& $NssmPath set EntregaBot AppRotateOnline 1
& $NssmPath set EntregaBot AppRotateSeconds 86400

Write-Host "Serviços instalados: EntregaBackend e EntregaBot (início automático)."