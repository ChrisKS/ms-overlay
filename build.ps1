# Builds MapleReader.zip: maple_reader.exe + bundled portable Tesseract.
# Run on Windows via build.bat. Needs Python 3.10+ on PATH and internet access.
# No installers are run and no admin rights are needed: Tesseract's installer is
# unpacked with 7-Zip (itself unpacked from its MSI, not installed).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$TessUrl  = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
$SevenUrl = "https://github.com/ip7z/7zip/releases/download/23.01/7z2301-x64.msi"
$Build    = Join-Path $PSScriptRoot "build"
$TessDir  = Join-Path $Build "tesseract"
$SevenDir = Join-Path $Build "7zip"
$Package  = Join-Path $Build "MapleReader"
$ZipPath  = Join-Path $PSScriptRoot "MapleReader.zip"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python not found on PATH." }
New-Item -ItemType Directory -Force $Build | Out-Null

Write-Host "==> Installing Python dependencies"
python -m pip install -r requirements.txt

if (-not (Test-Path "$TessDir\tesseract.exe")) {
    # 1) Find or fetch 7-Zip
    $SevenZip = @("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $SevenZip) {
        Write-Host "==> Fetching 7-Zip (unpacked locally, not installed)"
        $Msi = Join-Path $Build "7zip.msi"
        Invoke-WebRequest -Uri $SevenUrl -OutFile $Msi
        if (Test-Path $SevenDir) { Remove-Item -Recurse -Force $SevenDir }
        Start-Process msiexec -ArgumentList "/a `"$Msi`" /qn TARGETDIR=`"$SevenDir`"" -Wait
        $SevenZip = Get-ChildItem $SevenDir -Recurse -Filter 7z.exe | Select-Object -First 1 -ExpandProperty FullName
        if (-not $SevenZip) { throw "Could not unpack 7-Zip from MSI." }
    }

    # 2) Download Tesseract installer and unpack it with 7-Zip
    Write-Host "==> Downloading Tesseract"
    $Installer = Join-Path $Build "tesseract-setup.exe"
    Invoke-WebRequest -Uri $TessUrl -OutFile $Installer

    Write-Host "==> Unpacking Tesseract"
    if (Test-Path $TessDir) { Remove-Item -Recurse -Force $TessDir }
    & $SevenZip x -tNsis "-o$TessDir" $Installer -y | Out-Null
    if (-not (Test-Path "$TessDir\tesseract.exe")) { throw "Tesseract unpack failed (no tesseract.exe)." }
    if (-not (Test-Path "$TessDir\tessdata\eng.traineddata")) { throw "Tesseract unpack failed (no eng.traineddata)." }
}

Write-Host "==> Building exe with PyInstaller"
python -m PyInstaller --onefile --noconsole --noconfirm --name maple_reader `
    --distpath "$Build\dist" --workpath "$Build\pyi" --specpath "$Build" maple_reader.py
if (-not (Test-Path "$Build\dist\maple_reader.exe")) { throw "PyInstaller build failed." }

Write-Host "==> Assembling package"
if (Test-Path $Package) { Remove-Item -Recurse -Force $Package }
New-Item -ItemType Directory $Package | Out-Null
Copy-Item "$Build\dist\maple_reader.exe" $Package
Copy-Item $TessDir "$Package\tesseract" -Recurse
$T = "$Package\tesseract"
# Trim: installer leftovers, docs, helper tools, Java viewers, extra languages
Remove-Item -LiteralPath (Join-Path $T '$PLUGINSDIR') -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$T\doc" -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $T -File | Where-Object { $_.Extension -in ".html", ".jar" } | Remove-Item -Force
Get-ChildItem $T -Filter "*.exe" | Where-Object { $_.Name -ne "tesseract.exe" } | Remove-Item -Force
Get-ChildItem "$T\tessdata" -Filter "*.traineddata" |
    Where-Object { $_.BaseName -notin @("eng", "osd") } | Remove-Item -Force

Write-Host "==> Zipping"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path "$Package\*" -DestinationPath $ZipPath

Write-Host ""
Write-Host "Done: $ZipPath" -ForegroundColor Green
