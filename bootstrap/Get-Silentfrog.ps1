<#
.SYNOPSIS
  One-click installer for Silentfrog on Windows.

.DESCRIPTION
  Detects whether Python 3.12 / 3.13 / 3.14 is available via the `py`
  launcher. If not, downloads the official python.org installer and
  runs it silently for the current user. Then downloads the latest
  Silentfrog source from GitHub, places it under
  %LOCALAPPDATA%\Silentfrog\app, and runs install_silentfrog.py so the
  user ends up with a working .venv and a Silentfrog shortcut on the
  Desktop.

.NOTES
  Re-run safely: an existing install is overwritten in place except for
  its `.venv\` directory, which install_silentfrog.py keeps up to date.
  All actions are logged under %LOCALAPPDATA%\Silentfrog\bootstrap.log.
#>

#requires -Version 5.1

$ErrorActionPreference = "Stop"

$Owner = "developeter"
$Repo = "silentfrog"
$Branch = "dev"
$PythonInstallerUrl = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"

$InstallRoot = Join-Path $env:LOCALAPPDATA "Silentfrog"
$AppDir = Join-Path $InstallRoot "app"
$LogPath = Join-Path $InstallRoot "bootstrap.log"
$StagingDir = Join-Path $env:TEMP "silentfrog-bootstrap"

function Initialize-Logging {
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    "=== Silentfrog bootstrap $(Get-Date -Format o) ===" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
}

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message
    Write-Host $line
    $line | Out-File -FilePath $LogPath -Append -Encoding utf8
}

function Find-PythonVersion {
    # In Windows PowerShell 5.1, `2>&1` on a native command wraps each
    # stderr line as a NativeCommandError, which combined with
    # `$ErrorActionPreference = "Stop"` aborts on the first
    # missing-version probe. Use `py --list` once instead and parse
    # the (stdout-only) listing.
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        return $null
    }
    $listing = ""
    try {
        $listing = (& py --list) -join "`n"
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    foreach ($v in @("3.14", "3.13", "3.12")) {
        $pattern = "-V:" + [regex]::Escape($v) + "\b"
        if ($listing -match $pattern) {
            return $v
        }
    }
    return $null
}

function Install-Python {
    $installer = Join-Path $env:TEMP "python-installer.exe"
    Write-Log "Downloading Python installer from $PythonInstallerUrl"
    Invoke-WebRequest -Uri $PythonInstallerUrl -OutFile $installer -UseBasicParsing
    Write-Log "Running Python installer (silent, per-user, prepend PATH)"
    $args = "/quiet", "PrependPath=1", "InstallAllUsers=0"
    $proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Python installer exited with code $($proc.ExitCode)"
    }
    Write-Log "Python installed"
}

function Get-LatestSha {
    $url = "https://api.github.com/repos/$Owner/$Repo/commits/$Branch"
    Write-Log "Querying $url"
    $headers = @{ "Accept" = "application/vnd.github+json" }
    $response = Invoke-RestMethod -Uri $url -Headers $headers
    return $response.sha
}

function Save-SourceArchive {
    param([string]$Sha)
    $url = "https://github.com/$Owner/$Repo/archive/$Sha.zip"
    $archive = Join-Path $StagingDir "source.zip"
    Write-Log "Downloading source archive from $url"
    Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
    return $archive
}

function Expand-SourceArchive {
    param([string]$ArchivePath)
    $extractDir = Join-Path $StagingDir "extracted"
    if (Test-Path $extractDir) {
        Remove-Item $extractDir -Recurse -Force
    }
    Expand-Archive -Path $ArchivePath -DestinationPath $extractDir -Force
    $inner = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    if ($null -eq $inner) {
        throw "Archive did not contain a top-level directory"
    }
    return $inner.FullName
}

function Sync-AppDirectory {
    param([string]$SourceDir)
    Write-Log "Syncing source tree into $AppDir (preserving .venv)"
    if (-not (Test-Path $AppDir)) {
        New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    }
    # Wipe everything except the .venv so install_silentfrog.py can reuse it.
    Get-ChildItem -Path $AppDir -Force -Exclude ".venv" | Remove-Item -Recurse -Force
    Get-ChildItem -Path $SourceDir -Force | Copy-Item -Destination $AppDir -Recurse -Force
}

function Invoke-Installer {
    param([string]$PythonVersion, [string]$Sha)
    Write-Log "Running install_silentfrog.py with --revision $Sha"
    Push-Location $AppDir
    try {
        & py "-$PythonVersion" "install_silentfrog.py" "--revision" $Sha
        if ($LASTEXITCODE -ne 0) {
            throw "install_silentfrog.py exited with code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
    Write-Log "Installer finished"
}

function Main {
    Initialize-Logging
    Write-Log "Silentfrog bootstrap starting; target install at $AppDir"
    New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null

    $pyVersion = Find-PythonVersion
    if ($null -eq $pyVersion) {
        Write-Log "No supported Python found; installing"
        Install-Python
        $pyVersion = Find-PythonVersion
        if ($null -eq $pyVersion) {
            throw "Python installed but the 'py' launcher cannot find it. Open a new shell and rerun."
        }
    }
    Write-Log "Using Python $pyVersion"

    $sha = Get-LatestSha
    Write-Log "Target revision: $sha"
    $archive = Save-SourceArchive -Sha $sha
    $sourceDir = Expand-SourceArchive -ArchivePath $archive
    Sync-AppDirectory -SourceDir $sourceDir
    Invoke-Installer -PythonVersion $pyVersion -Sha $sha

    Remove-Item $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Log "Silentfrog bootstrap complete"
    Write-Host ""
    Write-Host "Silentfrog installed. Look for the 'Silentfrog' shortcut on your Desktop."
    Write-Host "If anything went wrong, see $LogPath."
}

try {
    Main
    Read-Host "Press Enter to close this window"
} catch {
    Write-Log ("ERROR: " + $_.Exception.Message)
    Write-Host ""
    Write-Host "Bootstrap failed. See $LogPath for details."
    Read-Host "Press Enter to close this window"
    exit 1
}
