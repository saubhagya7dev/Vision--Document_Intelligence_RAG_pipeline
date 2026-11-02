# Install the pinned Windows OCR runtime locally, without running its installer.
# Requires 7-Zip. Existing private .env values are left alone; configure the path
# printed at the end. No system PATH or registry changes are made.
param([string]$SevenZip = '')

$ErrorActionPreference = 'Stop'
$ocrProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $SevenZip) {
    $ocrSevenZipCommand = Get-Command 7z -ErrorAction SilentlyContinue
    if ($ocrSevenZipCommand) { $SevenZip = $ocrSevenZipCommand.Source }
    else { $SevenZip = Join-Path $env:ProgramFiles '7-Zip/7z.exe' }
}
if (-not (Test-Path -LiteralPath $SevenZip)) { throw 'Install 7-Zip or pass -SevenZip with its executable path.' }
$ocrDownloads = Join-Path $ocrProjectRoot '.tools/downloads'
$ocrRuntime = Join-Path $ocrProjectRoot '.tools/tesseract'
$ocrInstaller = Join-Path $ocrDownloads 'tesseract-5.4.0.exe'
$ocrExpectedHash = 'C885FFF6998E0608BA4BB8AB51436E1C6775C2BAFC2559A19B423E18678B60C9'
New-Item -ItemType Directory -Path $ocrDownloads -Force | Out-Null
if (-not (Test-Path -LiteralPath $ocrInstaller)) {
    Invoke-WebRequest -Uri 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe' -OutFile $ocrInstaller
}
if ((Get-FileHash -LiteralPath $ocrInstaller -Algorithm SHA256).Hash -ne $ocrExpectedHash) {
    throw 'Tesseract package checksum mismatch; refusing to extract.'
}
& $SevenZip x $ocrInstaller "-o$ocrRuntime" '-y' '-bso0' 'tesseract.exe' '*.dll' 'tessdata/*' 'doc/LICENSE'
if ($LASTEXITCODE -ne 0) { throw 'Tesseract runtime extraction failed.' }
$ocrExecutable = Join-Path $ocrRuntime 'tesseract.exe'
& $ocrExecutable --version
if ($LASTEXITCODE -ne 0) { throw 'Tesseract executable check failed.' }
& $ocrExecutable --list-langs
if ($LASTEXITCODE -ne 0) { throw 'Tesseract language check failed.' }
Write-Output ('Set this in your local .env: TESSERACT_EXECUTABLE="' + $ocrExecutable.Replace('\','/') + '"')
