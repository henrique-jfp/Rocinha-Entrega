param(
  [int]$Port = 8001
)

$ruleName = "Entrega Backend $Port"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
  Write-Host "Regra de firewall criada para TCP $Port."
} else {
  Write-Host "Regra de firewall já existe: $ruleName."
}