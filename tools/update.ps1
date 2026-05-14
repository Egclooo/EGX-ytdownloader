param(
  [Parameter(Mandatory = $true)]
  [string]$RepoRoot,

  [Parameter(Mandatory = $true)]
  [string]$ResultFile
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "YT Downloader Updater"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Git {
  param([string[]]$Arguments)

  $output = & git -C $RepoRoot @Arguments 2>&1
  $code = $LASTEXITCODE
  [pscustomobject]@{
    ExitCode = $code
    Output = ($output -join [Environment]::NewLine)
  }
}

try {
  Write-Host "YT Downloader update check" -ForegroundColor Green
  Write-Host "Repository: $RepoRoot"

  Write-Step "Checking local changes"
  $status = Invoke-Git @("status", "--porcelain")
  if ($status.ExitCode -ne 0) {
    throw $status.Output
  }
  if ($status.Output.Trim()) {
    Write-Host "Local changes were found. Update skipped to avoid overwriting work." -ForegroundColor Yellow
    Write-Host ""
    Write-Host $status.Output
    Start-Sleep -Seconds 3
    exit 0
  }

  Write-Step "Fetching GitHub updates"
  $fetch = Invoke-Git @("fetch", "--prune", "origin")
  if ($fetch.ExitCode -ne 0) {
    throw $fetch.Output
  }

  $branch = (Invoke-Git @("branch", "--show-current")).Output.Trim()
  if (-not $branch) {
    throw "Could not detect the current Git branch."
  }

  $local = (Invoke-Git @("rev-parse", "HEAD")).Output.Trim()
  $remote = (Invoke-Git @("rev-parse", "origin/$branch")).Output.Trim()

  if ($local -eq $remote) {
    Write-Host "Already up to date." -ForegroundColor Green
    Start-Sleep -Seconds 2
    exit 0
  }

  Write-Step "Pulling latest files"
  $pull = Invoke-Git @("pull", "--ff-only", "origin", $branch)
  if ($pull.ExitCode -ne 0) {
    throw $pull.Output
  }

  Write-Host $pull.Output
  Set-Content -LiteralPath $ResultFile -Value "updated" -Encoding ASCII
  Write-Host ""
  Write-Host "Update complete. The launcher will restart automatically." -ForegroundColor Green
  Start-Sleep -Seconds 2
  exit 0
} catch {
  Write-Host ""
  Write-Host "Update failed:" -ForegroundColor Red
  Write-Host $_.Exception.Message
  Write-Host ""
  Read-Host "Press Enter to continue startup"
  exit 1
}
