param(
    [string]$BackendEnvPath = ".\backend\.env",
    [string]$Portal = "bayut",
    [string]$ProxyList = "",
    [string]$UserDataDir = "",
    [string]$ProfileName = "",
    [switch]$UseChrome,
    [switch]$Headless
)

if (-not (Test-Path $BackendEnvPath)) {
    Write-Error "Could not find $BackendEnvPath"
    exit 1
}

$content = Get-Content $BackendEnvPath -Raw

function Set-Or-Append([string]$name, [string]$value) {
    $script:content = if ($script:content -match "(?m)^$name=") {
        [regex]::Replace($script:content, "(?m)^$name=.*$", "$name=$value")
    } else {
        $script:content.TrimEnd() + "`r`n$name=$value`r`n"
    }
}

Set-Or-Append "SCRAPER_STORAGE_STATE_PATH" "./runtime/scraper-state/$Portal.json"
Set-Or-Append "SCRAPER_STATE_DIR" "./runtime/scraper-state"

if ($UseChrome) {
    Set-Or-Append "SCRAPER_BROWSER_CHANNEL" "chrome"
}

Set-Or-Append "SCRAPER_HEADLESS" ($(if ($Headless) { "true" } else { "false" }))

if ($ProxyList) {
    Set-Or-Append "PROXY_LIST" $ProxyList
}

if ($UserDataDir) {
    Set-Or-Append "SCRAPER_USER_DATA_DIR" $UserDataDir
}

if ($ProfileName) {
    Set-Or-Append "SCRAPER_PROFILE_NAME" $ProfileName
}

Set-Content $BackendEnvPath $content
Write-Host "Updated scraper settings in $BackendEnvPath"
