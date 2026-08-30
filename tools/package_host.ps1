param(
    [string]$Python,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'

$RepositoryRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$HostRoot = Join-Path $RepositoryRoot 'host'
$BuildRoot = Join-Path $RepositoryRoot 'build\host-package'
$BuildEnvironment = Join-Path $BuildRoot '.venv'
$BuildPython = Join-Path $BuildEnvironment 'Scripts\python.exe'
$PyInstallerOutput = Join-Path $BuildRoot 'pyinstaller-dist'
$PyInstallerWork = Join-Path $BuildRoot 'pyinstaller-work'
$ArtifactRoot = Join-Path $RepositoryRoot 'dist\host'
$CachedPython = 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$SmokeTimeoutMilliseconds = 30000

function Resolve-PythonExecutable {
    if ($Python) {
        if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
            throw "Requested Python executable does not exist: $Python"
        }
        return [System.IO.Path]::GetFullPath($Python)
    }
    if (Test-Path -LiteralPath $CachedPython -PathType Leaf) {
        return $CachedPython
    }
    $PythonLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($null -ne $PythonLauncher) {
        $Python312 = & $PythonLauncher.Source -3.12 -c 'import sys; print(sys.executable)'
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $Python312 -PathType Leaf)) {
            return $Python312
        }
    }
    $SystemPython = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($null -ne $SystemPython) {
        return $SystemPython.Source
    }
    throw 'Python 3.11 or newer was not found. Pass -Python with an explicit executable.'
}

function Remove-ValidatedBuildDirectory {
    if (-not (Test-Path -LiteralPath $BuildRoot)) {
        return
    }
    $ResolvedBuildRoot = (Resolve-Path -LiteralPath $BuildRoot).Path
    $RepositoryPrefix = $RepositoryRoot.TrimEnd('\') + '\'
    if (-not $ResolvedBuildRoot.StartsWith($RepositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove build directory outside repository: $ResolvedBuildRoot"
    }
    Remove-Item -LiteralPath $ResolvedBuildRoot -Recurse -Force
}

function Invoke-PackagedSmokeTest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable
    )

    $Process = Start-Process -FilePath $Executable -ArgumentList '--smoke-test' -PassThru
    if (-not $Process.WaitForExit($SmokeTimeoutMilliseconds)) {
        $TaskKill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        & $TaskKill '/PID' $Process.Id '/T' '/F' | Out-Null
        throw "Packaged smoke test exceeded $SmokeTimeoutMilliseconds ms."
    }
    if ($Process.ExitCode -ne 0) {
        throw "Packaged smoke test failed with exit code $($Process.ExitCode)."
    }
}

$SourcePython = Resolve-PythonExecutable
Write-Host "Using Python: $SourcePython"
Remove-ValidatedBuildDirectory
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null

& $SourcePython -m venv $BuildEnvironment
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create build environment with $SourcePython."
}

& $BuildPython -m pip install -e "$HostRoot[dev]" -r (Join-Path $HostRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install host build dependencies.'
}

if (-not $SkipTests) {
    $PreviousQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = 'offscreen'
        & $BuildPython -m pytest (Join-Path $HostRoot 'tests') (Join-Path $RepositoryRoot 'test\test_protocol.py') -q
        if ($LASTEXITCODE -ne 0) {
            throw 'Host source test gate failed.'
        }
    }
    finally {
        $env:QT_QPA_PLATFORM = $PreviousQtPlatform
    }
}

& $BuildPython -m PyInstaller --clean --noconfirm --distpath $PyInstallerOutput --workpath $PyInstallerWork (Join-Path $HostRoot 'STM32SensorHost.spec')
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller build failed.'
}

$BuiltArtifactName = & $BuildPython -c 'from sensor_host.packaging import artifact_name; print(artifact_name())'
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to resolve the versioned artifact name.'
}
$BuiltArtifact = Join-Path $PyInstallerOutput $BuiltArtifactName
if (-not (Test-Path -LiteralPath $BuiltArtifact -PathType Leaf)) {
    throw "PyInstaller did not produce the expected artifact: $BuiltArtifact"
}
$FinalArtifact = Join-Path $ArtifactRoot $BuiltArtifactName
Copy-Item -LiteralPath $BuiltArtifact -Destination $FinalArtifact -Force

Invoke-PackagedSmokeTest -Executable $FinalArtifact

& $BuildPython -m sensor_host.packaging $FinalArtifact
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to write the artifact manifest.'
}

Write-Host "Packaged host: $FinalArtifact"
