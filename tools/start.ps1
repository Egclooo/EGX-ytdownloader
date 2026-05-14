param(
  [int]$RestartCount = 0
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$UpdateResult = Join-Path $RepoRoot ".update-result"
$InstallerCache = Join-Path $RepoRoot ".installer-cache"
$PythonInstallerUrl = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
$GitInstallerUrl = "https://github.com/git-for-windows/git/releases/latest/download/Git-64-bit.exe"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
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
  Write-Host "Downloading $Url"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing
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

function Find-Python {
  $commands = @(
    { py -3 -c "import sys; print(sys.executable)" 2>$null },
    { python -c "import sys; print(sys.executable)" 2>$null }
  )

  foreach ($command in $commands) {
    try {
      $candidate = (& $command | Select-Object -First 1)
      if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        return $candidate
      }
    } catch {
      continue
    }
  }

  $knownRoots = @(
    "$env:LocalAppData\Programs\Python",
    "$env:ProgramFiles\Python*",
    "${env:ProgramFiles(x86)}\Python*"
  )

  foreach ($root in $knownRoots) {
    if (-not $root) {
      continue
    }
    $candidate = Get-ChildItem -Path $root -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      Select-Object -First 1
    if ($candidate) {
      return $candidate.FullName
    }
  }

  return $null
}

function Install-Python {
  Write-Step "Python was not found. Installing Python 3.12"
  $winget = Get-Command winget -ErrorAction SilentlyContinue

  if ($winget) {
    winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) {
      Refresh-Path
      return
    }
    Write-Warning "winget Python install failed. Falling back to direct download."
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
    throw "Python was installed, but this launcher could not find python.exe. Open a new terminal and run start.bat again."
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
    winget install --id Git.Git --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) {
      Refresh-Path
      return [bool](Get-Command git -ErrorAction SilentlyContinue)
    }
    Write-Warning "winget Git install failed. Falling back to direct download."
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

  if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Step "Creating virtual environment"
    & $PythonExe -m venv (Join-Path $RepoRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
      throw "Could not create the virtual environment."
    }
  }
}

function Install-Dependencies {
  Write-Step "Installing Python dependencies"
  & $VenvPython -m ensurepip --upgrade
  if ($LASTEXITCODE -ne 0) {
    throw "Could not install or update pip."
  }

  & $VenvPython -m pip install --upgrade pip
  if ($LASTEXITCODE -ne 0) {
    throw "Could not update pip."
  }

  & $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
  if ($LASTEXITCODE -ne 0) {
    throw "Could not install project dependencies."
  }
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
  $script = Join-Path $PSScriptRoot "update.ps1"
  $arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$script`"",
    "-RepoRoot", "`"$RepoRoot`"",
    "-ResultFile", "`"$UpdateResult`""
  )

  $process = Start-Process powershell.exe -ArgumentList $arguments -Wait -PassThru
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
  Write-Step "Bootstrapping YT Downloader"
  $python = Ensure-Python
  Ensure-Venv -PythonExe $python
  Install-Dependencies
  Run-UpdaterWindow

  Write-Step "Starting app"
  & $VenvPython (Join-Path $RepoRoot "app.py")
  exit $LASTEXITCODE
} catch {
  Write-Host ""
  Write-Host "Startup failed:" -ForegroundColor Red
  Write-Host $_.Exception.Message
  Write-Host ""
  Read-Host "Press Enter to close"
  exit 1
}
