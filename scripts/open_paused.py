"""Open finished renders in Windows Media Player, paused, for the user to review.

Usage: python open_paused.py <video> [<video> ...]

Media Player has no start-paused switch and a background script can't focus its window, so this opens the file
with the default player, then pauses Media Player's own media session through Windows' media controls (the
same ones the volume flyout uses) and reads the state back. Run only after every step that rewrites the file:
an open file can't be replaced on Windows ("Access is denied").
"""
import os
import subprocess
import sys

PAUSE_PS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$M = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$mgr = Await ($M::RequestAsync()) ($M)
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
  $s = $mgr.GetSessions() | Where-Object { $_.SourceAppUserModelId -like '*ZuneMusic*' } | Select-Object -First 1
  if ($s -and $s.GetPlaybackInfo().PlaybackStatus -eq 'Playing') {
    $null = Await ($s.TryPauseAsync()) ([bool])
    Start-Sleep -Milliseconds 400
    "$($s.GetPlaybackInfo().PlaybackStatus)"; exit 0
  }
  Start-Sleep -Milliseconds 250
}
'no playing Media Player session found'; exit 1
"""

for path in sys.argv[1:]:
    if not os.path.exists(path):
        sys.exit(f"missing: {path}")
    os.startfile(path)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", PAUSE_PS], capture_output=True, text=True)
    print("opened", path, "-", (r.stdout.strip() or r.stderr.strip()[-300:]))
