# Puts an icon on the desktop that starts Twilight Ledger in a window of its
# own (ledger/window.py). What to start comes in on standard input as JSON:
# name, target, arguments, folder, icon. Says where the icon went.
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop ($in.name + '.lnk')
$icon = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$icon.TargetPath = $in.target
$icon.Arguments = $in.arguments
$icon.WorkingDirectory = $in.folder
$icon.IconLocation = $in.icon + ',0'
$icon.Description = $in.name
$icon.Save()
Write-Output ('<<TWILIGHT>>' + $path + '<<END>>')
