# Install the account-pool plugins for Hermes Agent on Windows from this checkout.
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 [-Provider NAME[,NAME...]] [-SetStrategy] [-NoTracker] [-NoTimer]
#
# -Provider     provider(s) to run setup for (default: anthropic). The timer balances every
#               provider with accounts whichever you name.
# -SetStrategy  set credential_pool_strategies.<provider>=fill_first in every profile that has
#               another value (needed by balance)
# -NoTracker    skip the session tracker (`hermes account <provider> who` stays empty)
# -NoTimer      skip the Task Scheduler task that runs `balance` every 5 minutes
#
# The Windows counterpart of install.sh: it copies the plugins into the Hermes home
# (%LOCALAPPDATA%\hermes, or HERMES_HOME), then runs `hermes account <provider> setup --yes`,
# the same step that follows `hermes plugins install`. No admin rights needed.
param(
    [string[]]$Provider = @("anthropic"),
    [switch]$SetStrategy,
    [switch]$NoTracker,
    [switch]$NoTimer
)
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$HermesBin = $null
$cmd = Get-Command hermes -ErrorAction SilentlyContinue
if ($cmd) { $HermesBin = $cmd.Source }
if (-not $HermesBin) {
    foreach ($name in @("hermes.exe", "hermes.cmd")) {
        $p = Join-Path (Join-Path $Root "bin") $name
        if (Test-Path $p) { $HermesBin = $p; break }
    }
}
if (-not $HermesBin) { Write-Error "hermes not found on PATH or in $Root\bin. Install Hermes Agent first."; exit 1 }
if (-not (Test-Path $Root)) { Write-Error "Hermes home not found: $Root"; exit 1 }
$env:HERMES_HOME = $Root

function Say([string]$text) { Write-Host ""; Write-Host "== $text" }

Say "Installing plugins into $Root\plugins"
$plugins = Join-Path $Root "plugins"
New-Item -ItemType Directory -Force -Path $plugins | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
foreach ($p in @("account-pool", "account-pool-tracker")) {
    if ($p -eq "account-pool-tracker" -and $NoTracker) { continue }
    $dest = Join-Path $plugins $p
    if (Test-Path $dest) {
        $item = Get-Item $dest -Force
        if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            $backups = Join-Path $Root "plugin-backups"           # outside plugins\: never loaded twice
            New-Item -ItemType Directory -Force -Path $backups | Out-Null
            Copy-Item -Recurse -Force $dest (Join-Path $backups "$p.$stamp")
            Write-Host "  previous $p backed up to $backups\$p.$stamp"
            Remove-Item -Recurse -Force $dest
        } else {
            & cmd.exe /d /c rmdir "$dest" | Out-Null            # a link: remove the link, never its target
        }
    }
    Copy-Item -Recurse -Force (Join-Path (Join-Path $Here "plugins") $p) $dest
    Get-ChildItem -Path $dest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Write-Host "  $p -> $dest"
}
& $HermesBin plugins enable account-pool | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "  enabled account-pool (default profile: the command)" }

# Profiles, tracker, timer and strategy: one implementation, shared with `hermes plugins install`.
$setup = @("--yes")
if (-not $NoTimer) { $setup += "--timer" }
if ($SetStrategy) { $setup += "--strategy" }
foreach ($prov in $Provider) {
    Say "hermes account $prov setup $($setup -join ' ')"
    & $HermesBin account $prov setup @setup
    if ($LASTEXITCODE -ne 0) { Write-Host "  setup reported a problem (see above); doctor below names it" }
}

Say "Check"
foreach ($prov in $Provider) { & $HermesBin account $prov doctor }
Write-Host ""
Write-Host "Done. Start with: hermes account help"
Write-Host ""
Write-Host "Hermes Desktop page (optional): restart Hermes Desktop so it loads the page's backend,"
Write-Host "then in Capabilities > Plugins switch on the Desktop half of account-pool. Accounts appears in the sidebar."
exit 0
