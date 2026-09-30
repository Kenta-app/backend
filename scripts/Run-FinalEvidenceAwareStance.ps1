$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$preparedRoot = Join-Path $repoRoot "output\stance_es_pe_v1\evidence_aware_spike_2026_09_28\prepared"
$dataRoot = Join-Path $repoRoot "output\stance_es_pe_v1\final_model_2026_09_28\training_data"
$runRoot = Join-Path $repoRoot "output\stance_es_pe_v1\final_model_2026_09_28"
$completedMarker = Join-Path $runRoot "best_model\serving_config.json"

if (Test-Path -LiteralPath $completedMarker) {
    throw "El modelo final ya existe y no se reemplazara: $completedMarker"
}

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

Push-Location $repoRoot
try {
    & $pythonPath ".\scripts\prepare_final_stance_training_data.py" `
        --prepared_dir $preparedRoot `
        --representation "retrieved_evidence" `
        --output_dir $dataRoot
    if ($LASTEXITCODE -ne 0) { throw "Fallo la preparacion del entrenamiento final." }

    & $pythonPath ".\scripts\train_stance_fixed_epochs.py" `
        --model_name "bert-base-multilingual-cased" `
        --train_stances (Join-Path $dataRoot "development_all_stances.csv") `
        --train_bodies (Join-Path $dataRoot "development_all_bodies.csv") `
        --output_dir $runRoot `
        --batch_size 4 `
        --lr 2e-5 `
        --epochs 4 `
        --max_length 192 `
        --seed 42
    if ($LASTEXITCODE -ne 0) { throw "Fallo el entrenamiento final." }
}
finally {
    Pop-Location
}

Write-Host "Modelo final entrenado y aun no evaluado prospectivamente: $runRoot"
