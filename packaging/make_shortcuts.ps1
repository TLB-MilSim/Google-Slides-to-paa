<#
    Creates Desktop and Start Menu shortcuts for TLB Intel Maker.
    Called by setup.bat; not meant to be run on its own.

    Pass -ScriptPath when launching from source; the argument string is built
    here rather than in the batch file, where nested quoting breaks -File
    parameter parsing.
#>
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$ScriptPath = "",
    [string]$WorkDir    = "",
    [string]$IconPath   = ""
)

$shell = New-Object -ComObject WScript.Shell
$arguments = if ($ScriptPath) { '"{0}" --gui' -f $ScriptPath } else { "" }

$places = @(
    [IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "TLB Intel Maker.lnk"),
    [IO.Path]::Combine([Environment]::GetFolderPath("StartMenu"), "Programs", "TLB Intel Maker.lnk")
)

$made = 0
foreach ($lnk in $places) {
    try {
        $dir = Split-Path $lnk -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

        $s = $shell.CreateShortcut($lnk)
        $s.TargetPath       = $Target
        $s.Arguments        = $arguments
        $s.WorkingDirectory = $WorkDir
        $s.Description      = "Google Slides to Arma 3 .paa briefing images"
        if ($IconPath -and (Test-Path $IconPath)) { $s.IconLocation = $IconPath }
        $s.Save()
        Write-Host "  created $lnk"
        $made++
    } catch {
        Write-Host "  could not create $lnk - $($_.Exception.Message)"
    }
}

if ($made -eq 0) { exit 1 }
