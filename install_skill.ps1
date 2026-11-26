param(
    [ValidateSet("Workspace", "Global", "Both")]
    [string]$Scope = "Workspace",
    [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$SuiteRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillSrc  = Join-Path $SuiteRoot "skills\sci-origin-pipeline"

if (-not (Test-Path $SkillSrc)) {
    throw "Skill source directory not found: $SkillSrc"
}

if ($Scope -in @("Workspace", "Both")) {
    $WsTarget = Join-Path $ProjectRoot ".agents\skills\sci-origin-pipeline"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $WsTarget) | Out-Null
    if (Test-Path $WsTarget) { Remove-Item -Recurse -Force $WsTarget }
    Copy-Item -Recurse -Force $SkillSrc $WsTarget
    Write-Host "[OK] Installed Workspace Skill -> $WsTarget" -ForegroundColor Green
}

if ($Scope -in @("Global", "Both")) {
    $GlobalPluginDir = Join-Path $HOME ".gemini\config\plugins\sci-origin-pipeline"
    New-Item -ItemType Directory -Force -Path $GlobalPluginDir | Out-Null
    Copy-Item -Force (Join-Path $SuiteRoot "plugin.json") $GlobalPluginDir
    Copy-Item -Force (Join-Path $SuiteRoot "README.md") $GlobalPluginDir
    if (Test-Path (Join-Path $GlobalPluginDir "assets")) { Remove-Item -Recurse -Force (Join-Path $GlobalPluginDir "assets") }
    if (Test-Path (Join-Path $GlobalPluginDir "skills")) { Remove-Item -Recurse -Force (Join-Path $GlobalPluginDir "skills") }
    Copy-Item -Recurse -Force (Join-Path $SuiteRoot "assets") (Join-Path $GlobalPluginDir "assets")
    Copy-Item -Recurse -Force (Join-Path $SuiteRoot "skills") (Join-Path $GlobalPluginDir "skills")
    Write-Host "[OK] Installed Global Antigravity Plugin -> $GlobalPluginDir" -ForegroundColor Cyan
}
