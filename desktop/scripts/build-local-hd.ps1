param(
    [Parameter(Mandatory = $true)][string]$NativeResources,
    [switch]$SkipDependencies,
    [switch]$SkipFrontend
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$desktopRoot = Join-Path $repoRoot 'desktop'
$NativeResources = [IO.Path]::GetFullPath($NativeResources)
$nativeDir = Join-Path $NativeResources 'backend\native'
$pin = Get-Content -LiteralPath (Join-Path $desktopRoot 'resources\native-core-source-windows.json') -Raw | ConvertFrom-Json
foreach ($entry in $pin.nativeFiles.PSObject.Properties) {
    $file = Join-Path $nativeDir $entry.Name
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) {
        throw "Native component does not match the project's pinned runtime: $($entry.Name)"
    }
}
$manifest = Get-Content -LiteralPath (Join-Path $nativeDir 'wechatdb_native_build.json') -Raw | ConvertFrom-Json
$rootCertificate = Join-Path $NativeResources 'signing\windows-private-pki-root.cer'
if ((Get-FileHash -LiteralPath $rootCertificate -Algorithm SHA256).Hash -ne $manifest.windowsPrivateRootSha256) {
    throw 'Native root certificate hash mismatch'
}
$env:WCE_NATIVE_CORE_ARTIFACT_DIR = $nativeDir
$env:WCE_WINDOWS_PRIVATE_ROOT_CERT_PATH = $rootCertificate
$env:WCE_WINDOWS_PRIVATE_ROOT_SHA256 = $manifest.windowsPrivateRootSha256
$env:UV_PROJECT_ENVIRONMENT = Join-Path $repoRoot '.build-venv'
$env:UV_CACHE_DIR = Join-Path $repoRoot '.build-cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot '.build-cache\python'
$env:ELECTRON_BUILDER_CACHE = Join-Path $repoRoot '.build-cache\electron-builder'
$env:PYTHONPATH = Join-Path $repoRoot 'src'
$env:PYTHONUTF8 = '1'
$env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'
$uvExecutable = (& python -c 'import uv; print(uv.find_uv_bin())').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $uvExecutable)) { throw 'Install uv first: python -m pip install uv' }
$env:PATH = (Split-Path $uvExecutable) + ';' + $env:PATH
function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}
$logDirectory = Join-Path $repoRoot '.build-logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Start-Transcript -Path (Join-Path $logDirectory ('build-hd-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')) | Out-Null
Push-Location $repoRoot
try {
    if (-not $SkipDependencies) {
        Invoke-Checked $uvExecutable @('sync', '--frozen', '--no-editable', '--extra', 'build', '--extra', 'voice-transcription', '--reinstall-package', 'wechat-decrypt-tool')
        Invoke-Checked 'npm.cmd' @('--prefix', 'frontend', 'ci', '--cache', (Join-Path $repoRoot '.build-cache\npm'), '--no-audit', '--no-fund')
        Invoke-Checked 'npm.cmd' @('--prefix', 'desktop', 'ci', '--cache', (Join-Path $repoRoot '.build-cache\npm'), '--no-audit', '--no-fund')
    }
    if (-not $SkipFrontend) { Invoke-Checked 'npm.cmd' @('--prefix', 'frontend', 'run', 'generate') }
    # These build directories are fixed descendants of this repository. Existing
    # build scripts clean them; never point their outputs at an installed app.
    Invoke-Checked 'node' @('desktop/scripts/copy-ui.cjs')
    Invoke-Checked 'node' @('desktop/scripts/build-backend.cjs')
    Invoke-Checked (Join-Path $desktopRoot 'resources\backend\wechat-backend.exe') @('--smoke-image-quality')
    Invoke-Checked 'node' @('desktop/scripts/build-icon.cjs')
    Push-Location $desktopRoot
    try {
        Invoke-Checked (Join-Path $desktopRoot 'node_modules\.bin\electron-builder.cmd') @('--win', '--x64', '--publish', 'never', '--config', 'local-hd-build.cjs')
    } finally { Pop-Location }
    $installer = Join-Path $desktopRoot 'dist\WeChatDataAnalysis-2.6.0-HD2-Setup.exe'
    if (-not (Test-Path -LiteralPath $installer)) { throw 'Installer was not generated' }
    $rootInstaller = Join-Path $repoRoot 'WeChatDataAnalysis-2.6.0-HD2-Setup.exe'
    Copy-Item -LiteralPath $installer -Destination $rootInstaller -Force
    Get-FileHash -LiteralPath $rootInstaller -Algorithm SHA256 | Format-List
} finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
