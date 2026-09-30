$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $repoRoot "scripts\evaluate_stance_v2_operational_legacy.py"
$modelPath = Join-Path $repoRoot "output\stance_es_pe_v2\final_model_2026_09_29"
$workspace = "C:\Users\sdiaz\Documents\Codex\2026-09-14\resolver-o-delimitar-el-componente-de"
$goldPath = Join-Path $workspace "outputs\evaluacion_final_2026_09_24\gold_congelado\Kenta_Stance_Peru_v1_evaluacion_final_gold.json"
$resultPath = Join-Path $workspace "outputs\stance_v2_challenge_05_2026_09_29\evaluacion_operacional_v2_2026_09_29"

foreach ($required in @($pythonPath, $entrypoint, $goldPath)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Falta un archivo necesario: $required"
    }
}
if (Test-Path -LiteralPath (Join-Path $resultPath "operational_v2_metrics.json")) {
    throw "La evaluación operativa v2 ya existe y no se repetirá."
}

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:TOKENIZERS_PARALLELISM = "false"

Push-Location $repoRoot
try {
    & $pythonPath $entrypoint `
        --gold $goldPath `
        --model-dir $modelPath `
        --output-dir $resultPath
    if ($LASTEXITCODE -ne 0) {
        throw "Falló el diagnóstico operativo v2."
    }
}
finally {
    Pop-Location
}

Write-Host "Diagnóstico operativo v2 guardado en: $resultPath"
