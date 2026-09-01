param(
    [ValidateSet("bayut", "dubizzle", "propertyfinder")]
    [string]$Portal = "bayut",
    [string]$UserDataDir = "$env:LocalAppData\Google\Chrome\User Data",
    [string]$ProfileName = "Default",
    [string]$BackendEnvPath = ".\backend\.env"
)

.\scripts\configure_scraper_env.ps1 `
    -BackendEnvPath $BackendEnvPath `
    -Portal $Portal `
    -UseChrome `
    -UserDataDir $UserDataDir `
    -ProfileName $ProfileName

Write-Host ""
Write-Host "Configured scraper to reuse Chrome profile:"
Write-Host "  User data dir: $UserDataDir"
Write-Host "  Profile name : $ProfileName"
Write-Host ""
Write-Host "Important:"
Write-Host "1. Close all Chrome windows before running the scraper, or Chrome may lock the profile."
Write-Host "2. Open Chrome normally first if you need to solve Bayut or Dubizzle manually."
Write-Host "3. Then rerun the smoke test."
