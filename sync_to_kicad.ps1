# RFsim - sync the plugin from this repository into KiCad 9 and KiCad 10.
#
# Copies plugins\*.py, plugins\assets and docs\RFSIM_SETTINGS.md into
#   <3rdparty\plugins>\com_github_nbalciunas_kicad-rfsim
# for each target below. The previous files are saved first in
#   <3rdparty>\plugin_backups\com_github_nbalciunas_kicad-rfsim\<yyyyMMdd-HHmmss>
# (outside the plugin directory; the 5 newest are kept). Python files that are
# in the plugin directory but no longer in the repository are removed (the
# backup holds them). Close KiCad before you sync.
#
# Usage:
#   .\sync_to_kicad.ps1                      # KiCad 9.0 and 10.0
#   .\sync_to_kicad.ps1 -Versions 10.0       # one version
#   .\sync_to_kicad.ps1 -Root "D:\KiCad"     # other root with <ver>\3rdparty\plugins
#                                            (or set $env:KICAD_3RDPARTY_ROOT)
#   .\sync_to_kicad.ps1 -WhatIf              # show what would be copied

param(
    [string[]]$Versions = @("9.0", "10.0"),
    # Root that holds <version>\3rdparty\plugins. Default: ...\Simulation tools\KiCad
    # (two levels above this repo); falls back to %APPDATA%\kicad when absent.
    [string]$Root = $(if ($env:KICAD_3RDPARTY_ROOT) { $env:KICAD_3RDPARTY_ROOT }
                      else { Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "KiCad" }),
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
$PluginDir = "com_github_nbalciunas_kicad-rfsim"
$Keep = 5

if (-not (Test-Path (Join-Path $Repo "plugins\board_reader.py"))) {
    throw "Run this script from the kicad-rfsim repository (plugins\board_reader.py not found)."
}

$running = Get-Process -Name "kicad", "pcbnew" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "[WARN] KiCad is running. Restart it after the sync to load the new plugin." -ForegroundColor Yellow
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
foreach ($v in $Versions) {
    $plugins = Join-Path $Root "$v\3rdparty\plugins"
    if (-not (Test-Path $plugins)) {
        $plugins = Join-Path $env:APPDATA "kicad\$v\3rdparty\plugins"
    }
    if (-not (Test-Path $plugins)) {
        Write-Host "[SKIP] KiCad $v : no 3rdparty\plugins directory found" -ForegroundColor Yellow
        continue
    }
    $dst = Join-Path $plugins $PluginDir
    Write-Host "`n[*] KiCad $v -> $dst" -ForegroundColor Cyan

    $bakRoot = Join-Path (Split-Path $plugins -Parent) "plugin_backups\$PluginDir"
    $bak = Join-Path $bakRoot $stamp
    if (Test-Path $dst) {
        if (-not $WhatIf) {
            New-Item -ItemType Directory -Path $bak -Force | Out-Null
            Get-ChildItem $dst -File -Filter *.py | Copy-Item -Destination $bak
            foreach ($d in "assets", "docs") {
                if (Test-Path (Join-Path $dst $d)) { Copy-Item (Join-Path $dst $d) $bak -Recurse }
            }
            Get-ChildItem $bakRoot -Directory | Sort-Object Name -Descending |
                Select-Object -Skip $Keep | Remove-Item -Recurse -Force
        }
        Write-Host "    backup: $bak" -ForegroundColor Gray
    } elseif (-not $WhatIf) {
        New-Item -ItemType Directory -Path $dst -Force | Out-Null
    }

    $files = Get-ChildItem (Join-Path $Repo "plugins") -File -Filter *.py
    $stale = @()
    if (Test-Path $dst) {
        $stale = Get-ChildItem $dst -File -Filter *.py | Where-Object { $files.Name -notcontains $_.Name }
    }
    foreach ($s in $stale) {
        Write-Host "    remove stale $($s.Name)" -ForegroundColor Yellow
        if (-not $WhatIf) { Remove-Item $s.FullName -Force }
    }
    foreach ($f in $files) {
        Write-Host "    $($f.Name)" -ForegroundColor Gray
        if (-not $WhatIf) { Copy-Item $f.FullName (Join-Path $dst $f.Name) -Force }
    }
    if (-not $WhatIf) {
        Copy-Item (Join-Path $Repo "plugins\assets") $dst -Recurse -Force
        New-Item -ItemType Directory -Path (Join-Path $dst "docs") -Force | Out-Null
        Copy-Item (Join-Path $Repo "docs\RFSIM_SETTINGS.md") (Join-Path $dst "docs") -Force
        # a stale byte-code cache from the old version is harmless but noisy
        Remove-Item (Join-Path $dst "__pycache__") -Recurse -Force -ErrorAction SilentlyContinue
    }

    # verify
    if (-not $WhatIf) {
        $bad = @()
        foreach ($f in $files) {
            if ((Get-FileHash $f.FullName).Hash -ne (Get-FileHash (Join-Path $dst $f.Name)).Hash) { $bad += $f.Name }
        }
        if ($bad.Count) { Write-Host "[ERROR] differ after copy: $($bad -join ', ')" -ForegroundColor Red }
        else { Write-Host "[OK] $($files.Count) files identical to the repository" -ForegroundColor Green }
    }
}
