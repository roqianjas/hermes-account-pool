# Remove the account-pool plugin (with the Hermes Desktop page and its session tracking in every
# profile), the retired account-pool-tracker plugin if it is still there, and the Task Scheduler
# task on Windows. The Windows counterpart of uninstall.sh.
#
#   powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 [-Yes]
#
# Accounts in the credential pool are NOT touched. A parked account stays in the pool, held out of
# rotation by Hermes until its park time ends (a park without an end time: up to 30 days); unpark it
# before uninstalling, or return every held account at once with `hermes auth reset <provider>`.
# -Yes skips the question about parked accounts.
param([switch]$Yes)
$ErrorActionPreference = "Stop"

$Root = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$HermesBin = $null
$cmd = Get-Command hermes -ErrorAction SilentlyContinue
if ($cmd) { $HermesBin = $cmd.Source } else { $HermesBin = Join-Path (Join-Path $Root "bin") "hermes.exe" }
$env:HERMES_HOME = $Root

$anyParked = $false
foreach ($f in @("account-pool-parking.json", "account-pool-parked.json")) {
    $parked = Join-Path $Root $f
    if ((Test-Path $parked) -and ((Get-Content -Raw -Encoding UTF8 $parked) -match '"id"')) { $anyParked = $true }
}
if ($anyParked -and -not $Yes) {
    Write-Host "WARNING: there are parked accounts. Hermes keeps them out of rotation until their park time ends."
    Write-Host "         Unpark them first (hermes account <provider> list), or afterwards: hermes auth reset <provider>"
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
        foreach ($p in @("account-pool", "account-pool-tracker")) {
            $link = Join-Path $d.FullName "plugins\$p"
            $item = Get-Item $link -Force -ErrorAction SilentlyContinue
            if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                if ($p -eq "account-pool-tracker") { & $HermesBin -p $d.Name plugins disable $p 2>$null | Out-Null }
                & cmd.exe /d /c rmdir "$link" | Out-Null          # the link only, never the plugin it points to
                Write-Host "$p link removed from $($d.Name)"
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
foreach ($f in @("account-pool-parking.json", "account-pool-parked.json", "account-pool-sessions.json", "account-pool-tokens.json",
                 "account-pool-history.jsonl", "account-pool-activity.jsonl", "account-pool-alerts.json",
                 "account-pool-state.json", "account-pool.json")) {
    $p = Join-Path $Root $f
    if (Test-Path $p) { Write-Host "  $p" }
}
Write-Host "credential_pool_strategies settings were left as they are."
exit 0
