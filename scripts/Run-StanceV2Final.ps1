$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $repoRoot "scripts\train_stance_v2_hierarchical.py"
$dataPath = Join-Path $repoRoot "data\processed\stance_es_pe_v2\development_v2.json"
$outputPath = Join-Path $repoRoot "output\stance_es_pe_v2\final_model_2026_09_29"
$freezeManifest = Join-Path $outputPath "model_freeze_manifest.json"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "No se encontró el Python del entorno virtual: $pythonPath"
}
if (-not (Test-Path -LiteralPath $dataPath)) {
    throw "No se encontró el corpus V2: $dataPath"
}
if (Test-Path -LiteralPath $freezeManifest) {
    throw "El candidato V2 ya está congelado y no se sobrescribirá: $freezeManifest"
}

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:TOKENIZERS_PARALLELISM = "false"

Push-Location $repoRoot
try {
    & $pythonPath $entrypoint `
        --data $dataPath `
        --output_dir $outputPath `
        --epochs 2 `
        --batch_size 2 `
        --eval_batch_size 8 `
        --gradient_accumulation_steps 2 `
        --learning_rate 5e-6 `
        --max_length 384 `
        --threshold 0.5 `
        --seed 42
    if ($LASTEXITCODE -ne 0) {
        throw "Falló el entrenamiento jerárquico final de Stance V2."
    }
}
finally {
    Pop-Location
}

Write-Host "Stance V2 congelado y pendiente de Challenge 05: $outputPath"
