# Builds the Fasway Android app with a new version number and Fasway-named APKs.
#
#   .\tool\build_apk.ps1            # 1.1.0 -> 1.1.1  (bug fixes / small changes)
#   .\tool\build_apk.ps1 -Minor     # 1.1.1 -> 1.2.0  (new features)
#   .\tool\build_apk.ps1 -Major     # 1.2.0 -> 2.0.0
#   .\tool\build_apk.ps1 -NoBump    # rebuild the current version
#
# Every build also raises the build number (Android needs it higher to install as an update), writes
# the same version to the laptop app (fasway/version.py), and puts the APKs in app\dist:
#   Fasway-v1.2.0-arm64.apk  (almost every phone)   Fasway-v1.2.0-arm32.apk  (old phones)
#   Fasway-v1.2.0-x86_64.apk (emulators)
param([switch]$Minor, [switch]$Major, [switch]$NoBump)
$ErrorActionPreference = "Stop"

$app = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $app
$pubspec = Join-Path $app "pubspec.yaml"

# ---- version: x.y.z+build in pubspec.yaml ----
$text = [IO.File]::ReadAllText($pubspec)
$m = [regex]::Match($text, '(?m)^version:\s*(\d+)\.(\d+)\.(\d+)\+(\d+)\s*$')
if (-not $m.Success) { throw "pubspec.yaml has no 'version: x.y.z+n' line" }
$x, $y, $z, $n = 1..4 | ForEach-Object { [int]$m.Groups[$_].Value }
if (-not $NoBump) {
    if ($Major) { $x++; $y = 0; $z = 0 } elseif ($Minor) { $y++; $z = 0 } else { $z++ }
    $n++
}
$version = "$x.$y.$z"
$text = [regex]::Replace($text, '(?m)^version:.*$', "version: $version+$n")
[IO.File]::WriteAllText($pubspec, $text)
[IO.File]::WriteAllText((Join-Path $root "fasway\version.py"),
    "`"`"`"Fasway version (shared with the Android app; set by app/tool/build_apk.ps1).`"`"`"`n__version__ = `"$version`"`nBUILD = $n`n")
Write-Host "Fasway $version (build $n)"

# ---- toolchain on E: ----
$env:ANDROID_HOME = "E:\dev\android-sdk"
$env:GRADLE_USER_HOME = "E:\dev\.gradle"
$env:PUB_CACHE = "E:\dev\.pub-cache"
$env:Path = "E:\dev\flutter\bin;" + $env:Path

Push-Location $app
try {
    # Flutter prints warnings on stderr; PowerShell must not treat those as errors, only the exit code counts
    $ErrorActionPreference = "Continue"
    flutter build apk --release --split-per-abi --dart-define=FASWAY_VERSION=$version --dart-define=FASWAY_BUILD=$n 2>&1 |
        ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "flutter build failed" }
    $ErrorActionPreference = "Stop"
} finally { Pop-Location }

# ---- Fasway-named copies ----
$out = Join-Path $app "build\app\outputs\flutter-apk"
$dist = Join-Path $app "dist"
New-Item -ItemType Directory -Force $dist | Out-Null
$names = @{ "arm64-v8a" = "arm64"; "armeabi-v7a" = "arm32"; "x86_64" = "x86_64" }
foreach ($abi in $names.Keys) {
    $src = Join-Path $out "app-$abi-release.apk"
    if (Test-Path $src) {
        $dst = Join-Path $dist "Fasway-v$version-$($names[$abi]).apk"
        Copy-Item $src $dst -Force
        Write-Host ("  {0}  ({1:N1} MB)" -f $dst, ((Get-Item $dst).Length / 1MB))
    }
}
