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

  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $output = & git -C $RepoRoot @Arguments 2>&1
    $code = $LASTEXITCODE
    [pscustomobject]@{
      ExitCode = $code
      Output = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    }
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
}

try {
  Write-Host "YT Downloader update check" -ForegroundColor Green
  Write-Host "Repository: $RepoRoot"

  Write-Step "Fetching GitHub updates"
  $fetch = Invoke-Git @("fetch", "--quiet", "--prune", "origin")
  if ($fetch.ExitCode -ne 0) {
    throw "Git fetch failed with exit code $($fetch.ExitCode).$([Environment]::NewLine)$($fetch.Output)"
  }

  $branchResult = Invoke-Git @("branch", "--show-current")
  if ($branchResult.ExitCode -ne 0) {
    throw "Could not detect the current Git branch.$([Environment]::NewLine)$($branchResult.Output)"
  }

  $branch = $branchResult.Output.Trim()
  if (-not $branch) {
    throw "Could not detect the current Git branch."
  }

  $localResult = Invoke-Git @("rev-parse", "HEAD")
  if ($localResult.ExitCode -ne 0) {
    throw "Could not read the local commit.$([Environment]::NewLine)$($localResult.Output)"
  }

  $remoteResult = Invoke-Git @("rev-parse", "origin/$branch")
  if ($remoteResult.ExitCode -ne 0) {
    throw "Could not read origin/$branch.$([Environment]::NewLine)$($remoteResult.Output)"
  }

  $local = $localResult.Output.Trim()
  $remote = $remoteResult.Output.Trim()

  if ($local -eq $remote) {
    Write-Host "Already up to date." -ForegroundColor Green
    Start-Sleep -Seconds 2
    exit 0
  }

  Write-Step "Pulling latest files"
  $pull = Invoke-Git @("pull", "--ff-only", "--autostash", "origin", $branch)
  if ($pull.ExitCode -ne 0) {
    throw "Git pull failed with exit code $($pull.ExitCode).$([Environment]::NewLine)$($pull.Output)"
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
