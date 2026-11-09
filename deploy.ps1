param([string]$PythonExe='python',[ValidateSet('both','optiland-cpu')][string]$Mode='both',[switch]$ConfigureOnly)
$ErrorActionPreference='Stop'
$deployRoot=$PSScriptRoot
Push-Location $deployRoot
try {
    & $PythonExe -c "import sys,struct;assert sys.version_info[:2]==(3,11) and struct.calcsize('P')==8,'Use Python 3.11 x64'"
    if($LASTEXITCODE -ne 0){throw 'Python 3.11 x64 is required.'}
    $venvPython=Join-Path $deployRoot '.venv\Scripts\python.exe'
    if(-not (Test-Path -LiteralPath $venvPython)) {
        & $PythonExe -m venv (Join-Path $deployRoot '.venv')
        if($LASTEXITCODE -ne 0){throw 'Failed to create the local environment.'}
    }
    if(-not $ConfigureOnly) {
        & $venvPython -m pip install --disable-pip-version-check --only-binary=:all: --no-deps -r (Join-Path $deployRoot 'requirements-baseline.txt')
        if($LASTEXITCODE -ne 0){throw 'Baseline installation failed. Do not silently change recorded versions.'}
        if($Mode -eq 'optiland-cpu'){$torchVersion='torch==2.6.0+cpu';$torchIndex='https://download.pytorch.org/whl/cpu'}
        else{$torchVersion='torch==2.6.0+cu118';$torchIndex='https://download.pytorch.org/whl/cu118'}
        & $venvPython -m pip install --disable-pip-version-check --no-deps $torchVersion --index-url $torchIndex
        if($LASTEXITCODE -ne 0){throw 'The selected PyTorch installation failed.'}
        $privateRuntime=Join-Path $deployRoot 'app\vendor\native_runtime'
        New-Item -ItemType Directory -Path $privateRuntime -Force | Out-Null
        & $venvPython -m pip install --disable-pip-version-check --only-binary=:all: --no-deps --upgrade 'scipy==1.16.3' --target $privateRuntime
        if($LASTEXITCODE -ne 0){throw 'Private SciPy installation failed.'}
        $analysisRuntime=Join-Path $deployRoot 'app/vendor/analysis_runtime'
        New-Item -ItemType Directory -Path $analysisRuntime -Force | Out-Null
        & $venvPython -m pip install --disable-pip-version-check --only-binary=:all: --no-deps --upgrade 'pyvista==0.46.4' 'scooby==0.10.2' --target $analysisRuntime
        if($LASTEXITCODE -ne 0){throw 'Private PyVista/Scooby installation failed.'}
        & $venvPython -m pip check
        if($LASTEXITCODE -ne 0){throw 'Installed global dependencies are inconsistent.'}
    }
    & $venvPython -I -B (Join-Path $deployRoot 'configure_runtime.py') --mode $Mode
    if($LASTEXITCODE -ne 0){throw 'Deployment is NOT ready. Read deployment_check.json; required failures cannot be ignored.'}
    Write-Host ('Verified deployment mode: '+$Mode+'. Read deployment_check.json for scope. Native 3D still requires a separate visual check.')
}
finally { Pop-Location }
