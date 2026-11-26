# Builds Mirage-Setup-<version>.exe on Windows (GitHub Actions runs this; see .github/workflows/build.yml).
#
# Needs: a python.org Python 3.13 (actions/setup-python sets $env:pythonLocation), the MSVC tools on PATH
# (cl.exe, rc.exe: ilammy/msvc-dev-cmd), and Inno Setup 6 (installed with Chocolatey if missing).
#
# Result: build\Mirage\ is the app folder exactly as it gets installed:
#   Mirage.exe            the launcher (Mirage's name and icon)
#   python*.dll, Lib\, DLLs\, tcl\, python.exe ...   a private copy of Python with every package Mirage needs
#   app\                  Mirage's own code (updated in place by Mirage's updater)
# and installer\out\Mirage-Setup-<version>.exe.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$build = Join-Path $root "build"
$out = Join-Path $build "Mirage"
New-Item -ItemType Directory -Force $build | Out-Null
Start-Transcript -Path (Join-Path $build "build.log") -Force | Out-Null

function Step($text) { Write-Host ""; Write-Host "==== $text ====" }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" } }

try {
    $py = $env:pythonLocation
    if (-not $py) { $py = Split-Path -Parent (Get-Command python).Source }
    $ver = (Get-Content (Join-Path $root "version.txt") -Raw).Trim()
    Write-Host "Mirage $ver, Python from $py"
    if (Test-Path $out) { Remove-Item -Recurse -Force $out }
    New-Item -ItemType Directory $out | Out-Null

    Step "Private Python"
    Get-ChildItem $py -File | Where-Object { $_.Name -match '^(python\.exe|pythonw\.exe|python3\d*\.dll|vcruntime140(_1)?\.dll|LICENSE\.txt)$' } |
        ForEach-Object { Copy-Item $_.FullName $out; Write-Host "  $($_.Name)" }
    Copy-Item -Recurse (Join-Path $py "DLLs") (Join-Path $out "DLLs")
    Copy-Item -Recurse (Join-Path $py "tcl") (Join-Path $out "tcl")
    robocopy (Join-Path $py "Lib") (Join-Path $out "Lib") /E /XD test tests __pycache__ site-packages idlelib turtledemo /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the Python library failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
    New-Item -ItemType Directory (Join-Path $out "Lib\site-packages") | Out-Null
    Set-Content (Join-Path $out "mirage-runtime.txt") "Mirage's own Python. Mirage $ver."
    $python = Join-Path $out "python.exe"
    & $python -I -c "import sys; print(sys.version); print(sys.prefix)"; Check "Starting the private Python"

    Step "Packages"
    & $python -I -m ensurepip --upgrade --default-pip; Check "ensurepip"
    & $python -I -m pip install --disable-pip-version-check --no-warn-script-location --upgrade pip; Check "Updating pip"
    & $python -I -m pip install --disable-pip-version-check --no-warn-script-location -r (Join-Path $root "requirements.txt") sherpa-onnx numpy
    Check "Installing Mirage's packages"
    & $python -I -m pip list --disable-pip-version-check

    Step "Mirage.exe"
    $v = @($ver.Split(".") | ForEach-Object { [int]$_ })
    while ($v.Count -lt 4) { $v += 0 }
    $esc = { param($p) $p -replace '\\', '\\' }
    $rc = @"
#include <winver.h>
1 ICON "$(& $esc (Join-Path $root 'assets\mirage.ico'))"
1 24 "$(& $esc (Join-Path $PSScriptRoot 'mirage.manifest'))"
1 VERSIONINFO
FILEVERSION $($v[0]),$($v[1]),$($v[2]),$($v[3])
PRODUCTVERSION $($v[0]),$($v[1]),$($v[2]),$($v[3])
FILEFLAGSMASK 0x3fL
FILEFLAGS 0x0L
FILEOS VOS_NT_WINDOWS32
FILETYPE VFT_APP
FILESUBTYPE 0x0L
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904b0"
    BEGIN
      VALUE "CompanyName", "Mirage"
      VALUE "FileDescription", "Mirage"
      VALUE "FileVersion", "$ver"
      VALUE "InternalName", "Mirage"
      VALUE "OriginalFilename", "Mirage.exe"
      VALUE "ProductName", "Mirage"
      VALUE "ProductVersion", "$ver"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x409, 1200
  END
END
"@
    $rcFile = Join-Path $build "mirage.rc"
    Set-Content -Path $rcFile -Value $rc -Encoding Ascii
    rc.exe /nologo /fo (Join-Path $build "mirage.res") $rcFile; Check "rc.exe"
    cl.exe /nologo /O2 /W3 /DUNICODE /D_UNICODE "/I$py\include" (Join-Path $PSScriptRoot "launcher.c") (Join-Path $build "mirage.res") `
        "/Fe$out\Mirage.exe" "/Fo$build\\" /link /SUBSYSTEM:WINDOWS /MANIFEST:NO "/LIBPATH:$py\libs" shell32.lib user32.lib
    Check "cl.exe"
    (Get-Item (Join-Path $out "Mirage.exe")).VersionInfo | Format-List FileDescription, ProductName, FileVersion

    Step "Mirage's code"
    $app = Join-Path $out "app"
    New-Item -ItemType Directory $app | Out-Null
    Get-ChildItem $root -File | Where-Object { $_.Extension -eq ".py" -or $_.Name -in @("requirements.txt", "version.txt", "README.md") } |
        ForEach-Object { Copy-Item $_.FullName $app }
    Copy-Item -Recurse (Join-Path $root "web") (Join-Path $app "web")
    Copy-Item -Recurse (Join-Path $root "assets") (Join-Path $app "assets")

    Step "Self-test"
    $env:MIRAGE_SELFTEST_OUT = Join-Path $build "selftest.txt"
    $p = Start-Process -FilePath (Join-Path $out "Mirage.exe") -ArgumentList "--selftest" -Wait -PassThru
    if (Test-Path $env:MIRAGE_SELFTEST_OUT) { Get-Content $env:MIRAGE_SELFTEST_OUT } else { Write-Host "(no self-test report)" }
    if ($p.ExitCode -ne 0) { throw "The self-test failed (exit code $($p.ExitCode))" }
    Get-ChildItem $out -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
    $size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
    Write-Host ("App folder: {0:N0} MB" -f $size)

    Step "Installer"
    $iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) {
        choco install innosetup -y --no-progress | Out-Host
        $iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    }
    $dist = Join-Path $PSScriptRoot "out"
    & $iscc "/DMyAppVersion=$ver" "/DSourceDir=$out" "/DOutDir=$dist" (Join-Path $PSScriptRoot "mirage.iss"); Check "Inno Setup"
    Get-ChildItem $dist | Format-Table Name, @{ n = "MB"; e = { "{0:N1}" -f ($_.Length / 1MB) } }
    Write-Host "BUILD OK"
}
finally {
    Stop-Transcript | Out-Null
}
