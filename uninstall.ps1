# Remove the account-pool plugins (with the Hermes Desktop page), the session tracker and the
# Task Scheduler task on Windows. The Windows counterpart of uninstall.sh.
#
#   powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 [-Yes]
#
# Accounts in the credential pool are NOT touched. Parked accounts stay in
# %LOCALAPPDATA%\hermes\account-pool-parked.json: unpark them before uninstalling if you want
# them back in rotation. -Yes skips the question about parked accounts.
param([switch]$Yes)
$ErrorActionPreference = "Stop"

$Root = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$HermesBin = $null
$cmd = Get-Command hermes -ErrorAction SilentlyContinue
if ($cmd) { $HermesBin = $cmd.Source } else { $HermesBin = Join-Path (Join-Path $Root "bin") "hermes.exe" }
$env:HERMES_HOME = $Root

$parked = Join-Path $Root "account-pool-parked.json"
if ((Test-Path $parked) -and ((Get-Content -Raw $parked) -match '"id"') -and -not $Yes) {
    Write-Host "WARNING: there are parked accounts. They will stay out of rotation after uninstall."
    Write-Host "         Unpark them first: hermes account <provider> list"
    $a = Read-Host "Continue anyway? [y/N]"
    if ($a -ne "y" -and $a -ne "Y") { exit 1 }
}

& schtasks.exe /Delete /F /TN "Hermes Account Balance" 2>$null | Out-Null
$timerDir = Join-Path $Root "account-pool-timer"
if (Test-Path $timerDir) { Remove-Item -Recurse -Force $timerDir }
Write-Host "timer removed"

$profiles = Join-Path $Root "profiles"
if (Test-Path $profiles) {
    foreach ($d in Get-ChildItem -Directory $profiles) {
        $link = Join-Path $d.FullName "plugins\account-pool-tracker"
        if (Test-Path $link) {
            $item = Get-Item $link -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                & $HermesBin -p $d.Name plugins disable account-pool-tracker 2>$null | Out-Null
                & cmd.exe /d /c rmdir "$link" | Out-Null          # the link only, never the tracker it points to
                Write-Host "tracker removed from $($d.Name)"
            }
        }
    }
}
& $HermesBin plugins disable account-pool-tracker 2>$null | Out-Null
& $HermesBin plugins disable account-pool 2>$null | Out-Null
# setup listed account-pool in every profile for the Accounts page backend
if (Test-Path $profiles) {
    foreach ($d in Get-ChildItem -Directory $profiles) {
        if (-not (Test-Path (Join-Path $d.FullName "config.yaml"))) { continue }
        $cur = (& $HermesBin -p $d.Name config get plugins.enabled --json 2>$null) -join ""
        if ($LASTEXITCODE -ne 0 -or $cur -notmatch '"account-pool"') { continue }
        $list = @($cur | ConvertFrom-Json | Where-Object { $_ -ne "account-pool" })
        $new = ConvertTo-Json -Compress -InputObject $list
        & $HermesBin -p $d.Name config set plugins.enabled $new | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "account-pool unlisted in $($d.Name)" }
    }
}
foreach ($p in @("account-pool", "account-pool-tracker")) {
    $dest = Join-Path $Root "plugins\$p"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
}
# Hermes Desktop's copy of the Accounts page (it would also go on the app's next start)
$page = Join-Path $Root "desktop-plugins\account-pool"
if (Test-Path (Join-Path $page ".hermes-package.json")) { Remove-Item -Recurse -Force $page }
Write-Host "plugins removed"

Write-Host ""
Write-Host "Kept (delete by hand if you no longer need them):"
foreach ($f in @("account-pool-parked.json", "account-pool-sessions.json", "account-pool-tokens.json",
                 "account-pool-history.jsonl", "account-pool-activity.jsonl", "account-pool-alerts.json",
                 "account-pool-state.json", "account-pool.json")) {
    $p = Join-Path $Root $f
    if (Test-Path $p) { Write-Host "  $p" }
}
Write-Host "credential_pool_strategies settings were left as they are."
exit 0
