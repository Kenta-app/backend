param(
    [ValidateSet(
        "oracle_evidence",
        "retrieved_evidence",
        "document_prefix",
        "oracle_evidence_no_title",
        "retrieved_evidence_no_title"
    )]
    [string]$Representation = "oracle_evidence",
    [int]$Seed = 42,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$preparedRoot = Join-Path $repoRoot "output\stance_es_pe_v1\evidence_aware_spike_2026_09_28\prepared"
$fncRoot = Join-Path $preparedRoot "$Representation\fnc"
$runRoot = Join-Path $repoRoot "output\stance_es_pe_v1\evidence_aware_spike_2026_09_28\runs\${Representation}_seed${Seed}"
$completedMarker = Join-Path $runRoot "best_model\serving_config.json"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "No se encontró el Python del entorno virtual: $pythonPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $preparedRoot "preparation_audit.json"))) {
    throw "Falta la auditoría de preparación. No se iniciará el entrenamiento."
}
if ((Test-Path -LiteralPath $completedMarker) -and -not $Force) {
    throw "La corrida ya está completa: $runRoot. Use -Force solo si desea reemplazarla."
}

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

Write-Host "Entrenando stance con representación '$Representation', semilla $Seed..."
Write-Host "Salida: $runRoot"

Push-Location $repoRoot
try {
    & $pythonPath -m app.ml.training.train_stance `
        --model_name "bert-base-multilingual-cased" `
        --train_stances (Join-Path $fncRoot "train_stances.csv") `
        --train_bodies (Join-Path $fncRoot "train_bodies.csv") `
        --val_stances (Join-Path $fncRoot "validation_stances.csv") `
        --val_bodies (Join-Path $fncRoot "validation_bodies.csv") `
        --test_stances (Join-Path $fncRoot "test_stances.csv") `
        --test_bodies (Join-Path $fncRoot "test_bodies.csv") `
        --output_dir $runRoot `
        --batch_size 4 `
        --lr 2e-5 `
        --epochs 6 `
        --max_length 192 `
        --patience 2 `
        --seed $Seed `
        --train_sampling shuffle
    if ($LASTEXITCODE -ne 0) {
        throw "El entrenamiento terminó con código $LASTEXITCODE"
    }

    & $pythonPath ".\scripts\summarize_evidence_aware_stance_run.py" `
        --run_dir $runRoot `
        --representation $Representation `
        --seed $Seed
    if ($LASTEXITCODE -ne 0) {
        throw "El entrenamiento terminó, pero falló el resumen automático."
    }
}
finally {
    Pop-Location
}

Write-Host "Listo. Revise: $(Join-Path $runRoot 'RUN_SUMMARY.md')"
