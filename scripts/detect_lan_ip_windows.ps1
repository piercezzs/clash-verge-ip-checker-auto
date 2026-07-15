$ErrorActionPreference = "SilentlyContinue"

$excludedAdapterName = "Loopback|vEthernet|Virtual|VMware|VirtualBox|Tailscale|ZeroTier|WireGuard|Wintun|Clash|Meta|Panda|OpenVPN|VPN|Bluetooth|蓝牙"

function Test-UsableIp {
  param([string] $Ip)
  if (-not $Ip) { return $false }
  if ($Ip -like "127.*") { return $false }
  if ($Ip -like "169.254.*") { return $false }
  if ($Ip -like "198.18.*" -or $Ip -like "198.19.*") { return $false }
  if ($Ip -like "0.*") { return $false }
  return $true
}

function Test-PrivateLanIp {
  param([string] $Ip)
  if ($Ip -like "10.*") { return $true }
  if ($Ip -like "192.168.*") { return $true }
  if ($Ip -match "^172\.(1[6-9]|2[0-9]|3[0-1])\.") { return $true }
  return $false
}

$blocks = (ipconfig) -join "`n" -split "(?:\r?\n){2,}"
$candidates = foreach ($block in $blocks) {
  $lines = $block -split "\r?\n" | Where-Object { $_.Trim() }
  if (-not $lines) { continue }

  $header = $lines[0]
  if ($header -match $excludedAdapterName) { continue }
  if ($block -match "Media disconnected|媒体已断开") { continue }
  if ($block -notmatch "(?:IPv4[^:]*):\s*(?<ip>(?:\d{1,3}\.){3}\d{1,3})") { continue }

  $ip = $Matches.ip
  if (-not (Test-UsableIp $ip)) { continue }

  [PSCustomObject]@{
    Ip = $ip
    HasGateway = [bool]($block -match "(?:Default Gateway|默认网关)[^:]*:\s*(?:\d{1,3}\.){3}\d{1,3}")
    IsPrivateLan = Test-PrivateLanIp $ip
  }
}

$selected = $candidates |
  Sort-Object @{ Expression = { -not $_.HasGateway } }, @{ Expression = { -not $_.IsPrivateLan } } |
  Select-Object -First 1

if ($selected) {
  $selected.Ip
}
