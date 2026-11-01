param(
    [ValidateSet('prepared','live')][string]$Mode = 'prepared',
    [string]$ModelPath = ''
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$galleryPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $galleryPython)) {
    python -m venv --system-site-packages .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or 3.12 is required.' }
}
$galleryExtra = if ($Mode -eq 'live') { '.[model]' } else { '.' }
& $galleryPython -m pip install -e $galleryExtra
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$gallerySeed = Join-Path $PSScriptRoot 'seed/gallery_data_120_siglip2_giant.zip'
if (-not (Test-Path -LiteralPath $gallerySeed)) { throw 'Place the verified Colab export at seed/gallery_data_120_siglip2_giant.zip.' }
$galleryArguments = @('-u','-m','gallery.cli','serve','--seed',$gallerySeed,'--mode',$Mode)
if ($Mode -eq 'live') {
    if (-not $ModelPath) { throw 'Pass -ModelPath pointing to the prepared checkpoint directory. See README.md.' }
    $galleryArguments += @('--model',$ModelPath)
}
& $galleryPython @galleryArguments
