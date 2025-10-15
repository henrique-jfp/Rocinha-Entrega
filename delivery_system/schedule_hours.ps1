param(
  [int]$StartHour = 5,
  [int]$StopHour = 19
)

$ErrorActionPreference = 'Stop'

# Cria tarefa para iniciar serviços às $StartHour diariamente
$triggerStart = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour $StartHour -Minute 0 -Second 0)
$actionStart = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -Command \"Start-Service EntregaBackend; Start-Service EntregaBot\""
Register-ScheduledTask -TaskName 'EntregaStart' -Trigger $triggerStart -Action $actionStart -RunLevel Highest -Force | Out-Null

# Cria tarefa para parar serviços às $StopHour diariamente
$triggerStop = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour $StopHour -Minute 0 -Second 0)
$actionStop = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -Command \"Stop-Service EntregaBackend; Stop-Service EntregaBot\""
Register-ScheduledTask -TaskName 'EntregaStop' -Trigger $triggerStop -Action $actionStop -RunLevel Highest -Force | Out-Null

Write-Host "Tarefas agendadas criadas: EntregaStart às $StartHour:00 e EntregaStop às $StopHour:00."