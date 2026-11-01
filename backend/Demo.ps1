param([string]$ModelPath='', [string]$DataPath='', [switch]$OpenBrowser, [ValidateSet('base','campus-run2')][string]$TextProfile='campus-run2')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$galleryPython=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $galleryPython)) {
    python -m venv --system-site-packages .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or 3.12 first.' }
}
& $galleryPython -c 'import importlib.util; assert all(importlib.util.find_spec(name) for name in ["gallery","torch","transformers","peft","fastapi","pillow_heif"])'
if ($LASTEXITCODE -ne 0) {
    & $galleryPython -m pip install -e '.[model]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not $ModelPath) { $ModelPath=Join-Path $env:USERPROFILE 'AppData/Local/SearchableGallery/models/siglip2-giant' }
if (-not (Test-Path -LiteralPath (Join-Path $ModelPath 'REVISION'))) { throw 'Cached Giant model not found. Pass -ModelPath; see QUICK_DEMO.md.' }
$gallerySeed=Join-Path $PSScriptRoot 'seed/gallery_demo_campus.zip'
if (-not (Test-Path -LiteralPath $gallerySeed)) { $gallerySeed=Join-Path $PSScriptRoot 'seed/gallery_data_120_siglip2_giant.zip' }
$galleryArgs=@('-u','-m','gallery.cli','serve','--demo','--mode','live','--model',$ModelPath,'--seed',$gallerySeed)
$galleryArgs+=@('--text-profile',$TextProfile)
if ($DataPath) { $galleryArgs+=@('--data',$DataPath) }
if ($OpenBrowser) { $galleryArgs+='--open-browser' }
Write-Host 'Loading the local model. When ready, open http://127.0.0.1:7861/presenter (no password in local demo mode).'
& $galleryPython @galleryArgs
