$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & uv venv --python 3.12 .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the project environment.' }
}
& uv pip install --python $taskPython -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Failed to install local dependencies.' }
foreach ($taskScript in @('prepare_models.py', 'repair_asr_tokenizer.py', 'verify_model_metadata.py', 'prepare_qwen_runtime.py')) {
    & $taskPython -X utf8 (Join-Path $PSScriptRoot "scripts/$taskScript")
    if ($LASTEXITCODE -ne 0) { throw "Preparation failed: $taskScript" }
}
& $taskPython -X utf8 -c 'from backend.app import local_config; local_config()'
if ($LASTEXITCODE -ne 0) { throw 'Failed to prepare the local connection configuration.' }
& (Join-Path $PSScriptRoot 'install-native-host.ps1')
Write-Host 'Local models and launcher are ready. Open YouTube and click Start subtitles.'
