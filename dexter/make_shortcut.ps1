# Create/refresh the "Dexter.lnk" desktop shortcut for THIS machine.
# Safe to re-run (same pattern as Jarvis's make_shortcuts.ps1).

$app = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$icon = Join-Path $app 'dexter.ico'
$ws = New-Object -ComObject WScript.Shell

$lnk = Join-Path $desktop 'Dexter.lnk'
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = (Join-Path $app 'Launch Dexter.bat')
$sc.WorkingDirectory = $app
if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
$sc.Description = 'Dexter - virtual Pokedex'
$sc.WindowStyle = 7
$sc.Save()
Write-Host "  created: $lnk"
