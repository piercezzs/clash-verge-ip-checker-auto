param(
  [Parameter(Mandatory = $true)]
  [string] $Url,

  [string] $TitlePattern = "Clash Verge IP Checker",

  [int] $TimeoutSeconds = 20
)

$ErrorActionPreference = "SilentlyContinue"

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class WindowFocus {
  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);

  [DllImport("user32.dll")]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

function Focus-MatchingWindow {
  param([string] $Pattern)

  $target = Get-Process |
    Where-Object {
      $_.MainWindowHandle -ne 0 -and
      $_.MainWindowTitle -and
      $_.MainWindowTitle -like "*$Pattern*"
    } |
    Select-Object -First 1

  if (-not $target) {
    return $false
  }

  [WindowFocus]::ShowWindow($target.MainWindowHandle, 9) | Out-Null
  [WindowFocus]::SetForegroundWindow($target.MainWindowHandle) | Out-Null
  return $true
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
      break
    }
  } catch {
    Start-Sleep -Milliseconds 500
  }
}

if (Focus-MatchingWindow -Pattern $TitlePattern) {
  exit 0
}

Start-Process $Url
