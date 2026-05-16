param(
  [int]$RestartCount = 0
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$UpdateResult = Join-Path $RepoRoot ".update-result"
$InstallerCache = Join-Path $RepoRoot ".installer-cache"
$BootstrapLog = Join-Path $RepoRoot ".bootstrap.log"
$RequiredPythonMajor = 3
$RequiredPythonMinor = 12
$PythonInstallerUrl = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
$GitInstallerUrl = "https://github.com/git-for-windows/git/releases/latest/download/Git-64-bit.exe"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message"
}

function Set-BootstrapProgress {
  param(
    [string]$Message,
    [int]$Percent
  )

  Write-Progress -Activity "YT Downloader startup" -Status $Message -PercentComplete $Percent
}

function Add-BootstrapLog {
  param([string]$Message)
  Add-Content -LiteralPath $BootstrapLog -Value $Message -Encoding UTF8
}

function Invoke-QuietCommand {
  param(
    [string]$Label,
    [int]$Percent,
    [string]$FilePath,
    [string[]]$Arguments
  )

  Write-Step $Label
  Set-BootstrapProgress -Message $Label -Percent $Percent
  Add-BootstrapLog ""
  Add-BootstrapLog "==> $Label"
  Add-BootstrapLog "$FilePath $($Arguments -join ' ')"

  $output = & $FilePath @Arguments 2>&1
  $code = $LASTEXITCODE
  if ($output) {
    Add-BootstrapLog (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine)
  }
  Add-BootstrapLog "Exit code: $code"

  if ($code -ne 0) {
    throw "$Label failed. See $BootstrapLog for details."
  }
}

function Refresh-Path {
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machinePath;$userPath"
}

function Download-Installer {
  param(
    [string]$Url,
    [string]$FileName
  )

  if (-not (Test-Path -LiteralPath $InstallerCache)) {
    New-Item -ItemType Directory -Path $InstallerCache | Out-Null
  }

  $target = Join-Path $InstallerCache $FileName
  Write-Step "Downloading installer"
  Set-BootstrapProgress -Message "Downloading installer" -Percent 16
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $previousProgressPreference = $ProgressPreference
  $ProgressPreference = "SilentlyContinue"
  Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing
  $ProgressPreference = $previousProgressPreference
  return $target
}

function Run-Installer {
  param(
    [string]$Path,
    [string[]]$Arguments
  )

  $process = Start-Process -FilePath $Path -ArgumentList $Arguments -Wait -PassThru
  if ($process.ExitCode -ne 0) {
    throw "Installer failed with exit code $($process.ExitCode): $Path"
  }
  Refresh-Path
}

function Test-PythonVersion {
  param([string]$PythonExe)

  if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) {
    return $false
  }

  $resolvedPython = $null
  try {
    $resolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
  } catch {
    return $false
  }

  $lowerPath = $resolvedPython.ToLowerInvariant()
  $excludedFragments = @(
    "\qgis ",
    "\qgis\",
    "\fl studio ",
    "\fl studio\",
    "\windowsapps\"
  )

  foreach ($fragment in $excludedFragments) {
    if ($lowerPath.Contains($fragment)) {
      Add-BootstrapLog "Skipping bundled or project-local Python candidate: $resolvedPython"
      return $false
    }
  }

  $probe = "import sys, venv, ensurepip; sys.stdout.write('%d.%d|%s' % (sys.version_info[0], sys.version_info[1], sys.executable))"

  try {
    $output = & $resolvedPython -I -E -c $probe 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0) {
      Add-BootstrapLog "Rejected Python candidate: $resolvedPython"
      if ($output) {
        Add-BootstrapLog (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine)
      }
      return $false
    }

    $result = (($output | Select-Object -Last 1).ToString()).Trim()
    $version = ($result -split "\|", 2)[0]
    return $version -eq "$RequiredPythonMajor.$RequiredPythonMinor"
  } catch {
    Add-BootstrapLog "Rejected Python candidate: $resolvedPython"
    Add-BootstrapLog $_.Exception.Message
    return $false
  }
}

function Add-PythonCandidate {
  param(
    [System.Collections.Generic.List[string]]$Candidates,
    [string]$Path
  )

  if (-not $Path) {
    return
  }

  $trimmed = $Path.Trim().Trim('"')
  if (-not $trimmed -or $Candidates.Contains($trimmed)) {
    return
  }

  $Candidates.Add($trimmed) | Out-Null
}

function Get-PythonFromPyLauncher {
  try {
    $versionArg = "-$RequiredPythonMajor.$RequiredPythonMinor"
    $output = & py $versionArg -I -E -c "import sys; sys.stdout.write(sys.executable)" 2>&1
    if ($LASTEXITCODE -eq 0 -and $output) {
      return (($output | Select-Object -Last 1).ToString()).Trim()
    }

    if ($output) {
      Add-BootstrapLog "Python launcher did not return a usable $RequiredPythonMajor.$RequiredPythonMinor executable:"
      Add-BootstrapLog (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine)
    }
  } catch {
    Add-BootstrapLog "Python launcher check failed: $($_.Exception.Message)"
  }

  return $null
}

function Find-Python {
  $candidates = New-Object System.Collections.Generic.List[string]

  $registryKeys = @(
    "HKCU:\Software\Python\PythonCore\$RequiredPythonMajor.$RequiredPythonMinor\InstallPath",
    "HKLM:\Software\Python\PythonCore\$RequiredPythonMajor.$RequiredPythonMinor\InstallPath",
    "HKLM:\Software\WOW6432Node\Python\PythonCore\$RequiredPythonMajor.$RequiredPythonMinor\InstallPath"
  )

  foreach ($keyPath in $registryKeys) {
    try {
      $key = Get-Item -LiteralPath $keyPath -ErrorAction SilentlyContinue
      if (-not $key) {
        continue
      }

      $installPath = $key.GetValue("")
      if ($installPath) {
        Add-PythonCandidate -Candidates $candidates -Path (Join-Path $installPath "python.exe")
      }
    } catch {
      continue
    }
  }

  $knownPaths = @(
    "$env:LocalAppData\Programs\Python\Python312\python.exe",
    "$env:ProgramFiles\Python312\python.exe",
    "${env:ProgramFiles(x86)}\Python312\python.exe"
  )

  foreach ($path in $knownPaths) {
    Add-PythonCandidate -Candidates $candidates -Path $path
  }

  $knownRoots = @(
    "$env:LocalAppData\Programs\Python",
    "$env:ProgramFiles",
    "${env:ProgramFiles(x86)}"
  )

  foreach ($root in $knownRoots) {
    if (-not $root -or -not (Test-Path -LiteralPath $root)) {
      continue
    }

    Get-ChildItem -Path (Join-Path $root "Python*") -Filter python.exe -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      ForEach-Object {
        Add-PythonCandidate -Candidates $candidates -Path $_.FullName
      }
  }

  Add-PythonCandidate -Candidates $candidates -Path (Get-PythonFromPyLauncher)

  $pathCommands = @("python3.12.exe", "python.exe")
  foreach ($commandName in $pathCommands) {
    $command = Get-Command $commandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
      Add-PythonCandidate -Candidates $candidates -Path $command.Source
    }
  }

  foreach ($candidate in $candidates) {
    try {
      $resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
      $venvDir = (Join-Path $RepoRoot ".venv").ToLowerInvariant()
      if ($resolvedCandidate.ToLowerInvariant().StartsWith($venvDir)) {
        Add-BootstrapLog "Skipping project virtual environment as a base Python candidate: $resolvedCandidate"
        continue
      }
    } catch {
      continue
    }

    if (Test-PythonVersion -PythonExe $candidate) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
  }

  return $null
}

function Install-Python {
  Write-Step "Python was not found. Installing Python 3.12"
  $winget = Get-Command winget -ErrorAction SilentlyContinue

  if ($winget) {
    try {
      Invoke-QuietCommand `
        -Label "Installing Python 3.12 with winget" `
        -Percent 12 `
        -FilePath "winget" `
        -Arguments @("install", "--id", "Python.Python.3.12", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements")
      Refresh-Path
      return
    } catch {
      Write-Warning "winget Python install failed. Falling back to direct download."
    }
  }

  $installer = Download-Installer -Url $PythonInstallerUrl -FileName "python-3.12.4-amd64.exe"
  Run-Installer -Path $installer -Arguments @(
    "/quiet",
    "InstallAllUsers=0",
    "PrependPath=1",
    "Include_launcher=1",
    "Include_pip=1"
  )
}

function Ensure-Python {
  $python = Find-Python
  if (-not $python) {
    Install-Python
    $python = Find-Python
  }
  if (-not $python) {
    throw "Python 3.12 was installed, but this launcher could not find python.exe. Open a new terminal and run start.bat again."
  }
  return $python
}

function Ensure-Git {
  $git = Get-Command git -ErrorAction SilentlyContinue
  if ($git) {
    return $true
  }

  Write-Step "Git was not found. Installing Git with winget"
  $winget = Get-Command winget -ErrorAction SilentlyContinue

  if ($winget) {
    try {
      Invoke-QuietCommand `
        -Label "Installing Git with winget" `
        -Percent 54 `
        -FilePath "winget" `
        -Arguments @("install", "--id", "Git.Git", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements")
      Refresh-Path
      return [bool](Get-Command git -ErrorAction SilentlyContinue)
    } catch {
      Write-Warning "winget Git install failed. Falling back to direct download."
    }
  } else {
    Write-Warning "winget is not available. Falling back to direct Git download."
  }

  $installer = Download-Installer -Url $GitInstallerUrl -FileName "Git-64-bit.exe"
  Run-Installer -Path $installer -Arguments @(
    "/VERYSILENT",
    "/NORESTART",
    "/NOCANCEL",
    "/SP-"
  )

  return [bool](Get-Command git -ErrorAction SilentlyContinue)
}

function Ensure-Venv {
  param([string]$PythonExe)

  $venvDir = Join-Path $RepoRoot ".venv"
  if (
    (Test-Path -LiteralPath $venvDir) -and
    (
      -not (Test-Path -LiteralPath $VenvPython) -or
      -not (Test-PythonVersion -PythonExe $VenvPython)
    )
  ) {
    Write-Step "Removing virtual environment created with the wrong Python version"
    $resolvedVenv = Resolve-Path -LiteralPath $venvDir
    if (-not $resolvedVenv.Path.StartsWith($RepoRoot.Path)) {
      throw "Refusing to remove virtual environment outside the project folder."
    }
    Remove-Item -LiteralPath $resolvedVenv.Path -Recurse -Force
  }

  if (-not (Test-Path -LiteralPath $VenvPython)) {
    Invoke-QuietCommand `
      -Label "Creating virtual environment" `
      -Percent 28 `
      -FilePath $PythonExe `
      -Arguments @("-m", "venv", $venvDir)
  }
}

function Install-Dependencies {
  Invoke-QuietCommand `
    -Label "Preparing pip" `
    -Percent 38 `
    -FilePath $VenvPython `
    -Arguments @("-m", "ensurepip", "--upgrade")

  Invoke-QuietCommand `
    -Label "Updating pip" `
    -Percent 46 `
    -FilePath $VenvPython `
    -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip")

  Invoke-QuietCommand `
    -Label "Installing Python dependencies" `
    -Percent 62 `
    -FilePath $VenvPython `
    -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $RepoRoot "requirements.txt"))
}

function Run-UpdaterWindow {
  if (Test-Path -LiteralPath $UpdateResult) {
    Remove-Item -LiteralPath $UpdateResult -Force
  }

  $hasGit = Ensure-Git
  if (-not $hasGit) {
    return
  }

  if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
    Write-Warning "This folder is not a Git checkout. GitHub update check skipped."
    return
  }

  Write-Step "Opening update window"
  $script = Join-Path $PSScriptRoot "updater_app.py"
  $arguments = @(
    "`"$script`"",
    "--repo-root", "`"$RepoRoot`"",
    "--result-file", "`"$UpdateResult`""
  )

  $process = Start-Process $VenvPython -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
  if ($process.ExitCode -ne 0) {
    Write-Warning "The update window ended with exit code $($process.ExitCode). Continuing startup."
  }

  if (Test-Path -LiteralPath $UpdateResult) {
    $result = Get-Content -LiteralPath $UpdateResult -Raw
    Remove-Item -LiteralPath $UpdateResult -Force
    if ($result.Trim() -eq "updated") {
      exit 20
    }
  }
}

try {
  Set-Content -LiteralPath $BootstrapLog -Value "YT Downloader bootstrap log" -Encoding UTF8
  Write-Step "Bootstrapping YT Downloader"
  Set-BootstrapProgress -Message "Bootstrapping YT Downloader" -Percent 4
  $python = Ensure-Python
  Ensure-Venv -PythonExe $python
  Install-Dependencies
  Set-BootstrapProgress -Message "Checking for updates" -Percent 78
  Run-UpdaterWindow

  Write-Step "Starting app"
  Set-BootstrapProgress -Message "Starting app" -Percent 96
  Write-Progress -Activity "YT Downloader startup" -Completed
  & $VenvPython (Join-Path $RepoRoot "app.py")
  exit $LASTEXITCODE
} catch {
  Write-Progress -Activity "YT Downloader startup" -Completed
  Write-Host ""
  Write-Host "Startup failed:" -ForegroundColor Red
  Write-Host $_.Exception.Message
  Write-Host "Details were saved to $BootstrapLog"
  Write-Host ""
  Read-Host "Press Enter to close"
  exit 1
}
