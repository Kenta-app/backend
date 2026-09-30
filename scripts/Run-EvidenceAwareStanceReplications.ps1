$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "Run-EvidenceAwareStanceSpike.ps1"
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runsRoot = Join-Path $repoRoot "output\stance_es_pe_v1\evidence_aware_spike_2026_09_28\runs"
$comparisonRoot = Join-Path $repoRoot "output\stance_es_pe_v1\evidence_aware_spike_2026_09_28\multiseed"
$representations = @(
    "document_prefix",
    "retrieved_evidence",
    "oracle_evidence_no_title",
    "retrieved_evidence_no_title"
)
$seeds = @(123, 2026)

foreach ($representation in $representations) {
    foreach ($seed in $seeds) {
        $marker = Join-Path $runsRoot "${representation}_seed${seed}\best_model\serving_config.json"
        if (Test-Path -LiteralPath $marker) {
            Write-Host "Omitiendo corrida ya completa: $representation / $seed"
            continue
        }
        Write-Host "=== $representation / seed $seed ==="
        & $runner -Representation $representation -Seed $seed
    }
}

Push-Location $repoRoot
try {
    & $pythonPath ".\scripts\aggregate_evidence_aware_stance_runs.py" `
        --runs_dir $runsRoot `
        --output_dir $comparisonRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Las corridas terminaron, pero falló la agregación multisemilla."
    }
}
finally {
    Pop-Location
}

Write-Host "Replicaciones completas: $(Join-Path $comparisonRoot 'MULTISEED_COMPARISON.md')"
