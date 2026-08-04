# Regenerate Jarvis desktop shortcuts with paths correct for THIS machine.
# Run after copying the project to a new PC (shortcuts store absolute paths and
# don't survive a move/USB copy). Safe to re-run.

$app = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$icon = Join-Path $app 'jarvis.ico'
$ws = New-Object -ComObject WScript.Shell

function New-Lnk($name, $target, $desc) {
    $lnk = Join-Path $desktop $name
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = (Join-Path $app $target)
    $sc.WorkingDirectory = $app
    if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
    $sc.Description = $desc
    $sc.WindowStyle = 1
    $sc.Save()
    Write-Host "  created: $lnk"
}

Write-Host "Regenerating Jarvis shortcuts on $desktop ..."
New-Lnk 'Jarvis.lnk'              'Launch Jarvis.bat'        'Launch Jarvis (classic window).'
New-Lnk 'Jarvis HUD.lnk'         'Launch Jarvis HUD.bat'    'Launch Jarvis with the WebGL glass HUD.'
New-Lnk 'Regenerate Jarvis URL.lnk' 'Regenerate Online URL.bat' 'Start remote access and generate a fresh public URL (copied to clipboard).'
Write-Host "Done."
