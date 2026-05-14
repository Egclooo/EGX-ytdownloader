param(
  [int]$RestartCount = 0
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$UpdateResult = Join-Path $RepoRoot ".update-result"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
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
  Write-Step "Python was not found. Installing Python 3.12 with winget"
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "Python is not installed and winget is not available. Install Python 3.12 from https://www.python.org/downloads/windows/ and run start.bat again."
  }

  winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    throw "Python installation failed. Run start.bat again after installing Python manually."
  }
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
  if (-not $winget) {
    Write-Warning "Git is not installed and winget is not available. GitHub updates will be skipped."
    return $false
  }

  winget install --id Git.Git --source winget --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Git installation failed. GitHub updates will be skipped."
    return $false
  }

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
