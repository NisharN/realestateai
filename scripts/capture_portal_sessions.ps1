param(
    [ValidateSet("bayut", "dubizzle", "propertyfinder", "all")]
    [string]$Portal = "all",
    [string]$PythonExe = ".\backend\venv\Scripts\python.exe"
)

$targets = if ($Portal -eq "all") {
    @("bayut", "dubizzle", "propertyfinder")
} else {
    @($Portal)
}

foreach ($target in $targets) {
    Write-Host ""
    Write-Host "Opening browser for $target ..."
    & $PythonExe ".\scripts\capture_scraper_session.py" $target
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to capture session for $target"
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "Session capture complete."
