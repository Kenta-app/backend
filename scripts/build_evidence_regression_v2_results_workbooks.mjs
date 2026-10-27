import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const args = process.argv.slice(2);
const valueAfter = (flag, fallback) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : fallback;
};

const inputDir = valueAfter("--input-dir", "output/evidence_end_to_end_regression_v2_analysis_2026_10_25");
const outputDir = valueAfter("--output-dir", "outputs/evidence-retrieval-regression-v2-results-2026-10-25");
const previewDir = valueAfter("--preview-dir", "output/evidence_retrieval_regression_v2_results_preview");

const fontFamily = "Arial";
const bodyFont = { name: fontFamily, size: 10, color: "#172033" };
const headerFormat = {
  fill: "#243B53",
  font: { name: fontFamily, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "inside", style: "thin", color: "#FFFFFF" },
};
const sectionFormat = {
  fill: "#DCE6EF",
  font: { name: fontFamily, size: 10, bold: true, color: "#172033" },
};

async function csvValues(fileName, sheetName = "Data") {
  const csvText = (await fs.readFile(path.join(inputDir, fileName), "utf8")).replace(/^\uFEFF/, "");
  const temp = await Workbook.fromCSV(csvText, { sheetName });
  return temp.worksheets.getItem(sheetName).getUsedRange(true).values;
}

function rowsAsObjects(values) {
  const headers = values[0].map(String);
  return values.slice(1).map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index]])));
}

function selectColumns(values, columns) {
  const headers = values[0].map(String);
  const indices = columns.map((column) => {
    const index = headers.indexOf(column);
    if (index < 0) throw new Error(`Missing column ${column}`);
    return index;
  });
  return [columns, ...values.slice(1).map((row) => indices.map((index) => row[index]))];
}

function addValuesSheet(workbook, name, values) {
  const sheet = workbook.worksheets.add(name);
  sheet.getRange("A1").write(values);
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
  const rows = values.length;
  const cols = values[0].length;
  sheet.getRangeByIndexes(0, 0, rows, cols).format.font = bodyFont;
  sheet.getRangeByIndexes(0, 0, 1, cols).format = headerFormat;
  sheet.getRangeByIndexes(0, 0, 1, cols).format.rowHeight = 38;
  if (rows > 1) sheet.getRangeByIndexes(1, 0, rows - 1, cols).format.verticalAlignment = "top";
  for (let col = 0; col < cols; col += 1) {
    sheet.getRangeByIndexes(0, col, rows, 1).format.columnWidth = 17;
  }
  return sheet;
}

function formatComparisonSheet(sheet, values, wrapColumns) {
  const rows = values.length;
  for (const [columnIndex, width] of wrapColumns) {
    sheet.getRangeByIndexes(0, columnIndex, rows, 1).format.columnWidth = width;
    if (rows > 1) sheet.getRangeByIndexes(1, columnIndex, rows - 1, 1).format.wrapText = true;
  }
  if (rows > 1) sheet.getRangeByIndexes(1, 0, rows - 1, values[0].length).format.rowHeight = 58;
}

function fmtPct(value) {
  return `${(100 * value).toFixed(1)}%`;
}

function fmtKappa(value) {
  return value == null ? "no estimable" : value.toFixed(3);
}

function confusionMatrix(sourceValues) {
  const rows = rowsAsObjects(sourceValues).filter((row) => String(row.consensus_stance || "").trim());
  const labels = ["supports", "refutes", "discusses", "unrelated"];
  const matrix = labels.map((gold) => labels.map((predicted) => rows.filter(
    (row) => row.consensus_stance === gold && row.model_stance === predicted,
  ).length));
  return [
    ["Humano / sistema", ...labels, "Total"],
    ...labels.map((label, index) => [label, ...matrix[index], matrix[index].reduce((a, b) => a + b, 0)]),
    ["Total", ...labels.map((_, col) => matrix.reduce((sum, row) => sum + row[col], 0)), rows.length],
  ];
}

async function buildReport(summary, sourceValues, coverageValues) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Resumen");
  sheet.showGridLines = false;
  sheet.getRange("A2:F2").merge();
  sheet.getRange("A2").values = [["Regresión de recuperación de evidencia — resultados previos a adjudicación"]];
  sheet.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
  sheet.getRange("A4:E4").values = [["Área", "Métrica", "Resultado", "Base", "Lectura"]];
  sheet.getRange("A4:E4").format = headerFormat;

  const sourceAgreement = summary.source_agreement;
  const quality = summary.retrieval_source_quality_consensus_only;
  const stance = summary.system_stance_consensus_only;
  const coverageAgreement = summary.coverage_agreement;
  const coverage = summary.coverage_consensus_only;
  const systemRun = summary.system_run;
  const falseEmptyRate = coverage.zero_source_consensus_n ? coverage.false_empty_n / coverage.zero_source_consensus_n : null;
  const metricRows = [
    ["Ejecución", "Publicaciones con al menos una fuente", systemRun.retrieval_success_rate, `${systemRun.retrieval_success_n}/${summary.coverage_cases}`, "Cumple el criterio registrado de al menos 16/20."],
    ["Fuentes", "Acuerdo de evaluabilidad", sourceAgreement.evaluability_exact, `${summary.source_pairs} pares`, `κ=${fmtKappa(sourceAgreement.evaluability_kappa)}.`],
    ["Fuentes", "Acuerdo de postura", sourceAgreement.stance_exact_among_both_evaluable, `${sourceAgreement.both_evaluable_n} pares evaluables`, `κ=${fmtKappa(sourceAgreement.stance_kappa_among_both_evaluable)}; quedan ${sourceAgreement.needs_adjudication_n} pares.`],
    ["Fuentes", "Precisión de recuperación", quality.precision, `${quality.relevant_n}/${quality.evaluable_consensus_n}`, "Cumple preliminarmente el mínimo registrado de 90%; solo usa consenso exacto."],
    ["Postura", "Exactitud contra consenso", stance.accuracy, `${stance.accuracy_count}/${stance.n}`, "Queda por debajo del criterio registrado de 75%; puede cambiar tras adjudicación."],
    ["Postura", "Macro-F1 de clases observadas", stance.macro_f1_observed_gold_classes, `${stance.n} pares`, "En el consenso solo aparecen supports y discusses."],
    ["Cobertura", "Acuerdo exacto", coverageAgreement.coverage_exact, `${summary.coverage_cases} casos`, `κ=${fmtKappa(coverageAgreement.coverage_kappa)}; quedan ${coverageAgreement.needs_adjudication_n} casos.`],
    ["Cobertura", "Casos con evidencia útil", coverage.useful_coverage_rate, `${coverage.useful_coverage_n}/${coverage.evidence_exists_n}`, "Cumple preliminarmente el criterio registrado de 80%; solo usa casos consensuados."],
    ["Cobertura", "Casos con cobertura suficiente", coverage.sufficient_coverage_rate, `${coverage.sufficient_coverage_n}/${coverage.evidence_exists_n}`, "Mide cobertura completa, no solo utilidad."],
    ["Vacíos", "Tasa de vacíos falsos", falseEmptyRate, `${coverage.false_empty_n}/${coverage.zero_source_consensus_n}`, "No cumple el máximo registrado de 20%."],
    ["Pendiente", "Desacuerdos de fuentes", sourceAgreement.needs_adjudication_n, `${summary.source_pairs} pares`, "Excluir de la conclusión final hasta adjudicar."],
    ["Pendiente", "Desacuerdos de cobertura", coverageAgreement.needs_adjudication_n, `${summary.coverage_cases} casos`, "Excluir de la conclusión final hasta adjudicar."],
  ];
  sheet.getRange("A5").write(metricRows);
  sheet.getRange("A5:E16").format.font = bodyFont;
  sheet.getRange("A5:E16").format.verticalAlignment = "top";
  sheet.getRange("B5:B16").format.wrapText = true;
  sheet.getRange("E5:E16").format.wrapText = true;
  for (const row of [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]) sheet.getRange(`C${row}`).format.numberFormat = "0.0%";
  sheet.getRange("A:A").format.columnWidth = 15;
  sheet.getRange("B:B").format.columnWidth = 38;
  sheet.getRange("C:C").format.columnWidth = 16;
  sheet.getRange("D:D").format.columnWidth = 23;
  sheet.getRange("E:E").format.columnWidth = 64;
  sheet.getRange("A5:A16").format.fill = "#EEF3F7";
  sheet.getRange("A5:E16").format.rowHeight = 36;

  const matrix = confusionMatrix(sourceValues);
  sheet.getRange("G4:L4").merge();
  sheet.getRange("G4").values = [["Matriz de confusión de postura (consenso exacto)"]];
  sheet.getRange("G4:L4").format = sectionFormat;
  sheet.getRange("G5").write(matrix);
  sheet.getRange("G5:L5").format = headerFormat;
  sheet.getRange("G6:L10").format.font = bodyFont;
  sheet.getRange("G:G").format.columnWidth = 24;
  sheet.getRange("H:L").format.columnWidth = 14;

  sheet.getRange("G12:L12").merge();
  sheet.getRange("G12").values = [["Lectura defendible"]];
  sheet.getRange("G12:L12").format = sectionFormat;
  sheet.getRange("G13:L17").merge(true);
  sheet.getRange("G13:G17").values = [
    [`La recuperación subió a ${systemRun.retrieval_success_n}/${summary.coverage_cases} casos (${fmtPct(systemRun.retrieval_success_rate)}), frente a 11/20 en el piloto anterior.`],
    [`La cobertura útil preliminar es ${coverage.useful_coverage_n}/${coverage.evidence_exists_n} (${fmtPct(coverage.useful_coverage_rate)}), pero hay ${coverageAgreement.needs_adjudication_n} casos sin consenso.`],
    [`La precisión consensuada de las fuentes es ${quality.relevant_n}/${quality.evaluable_consensus_n} (${fmtPct(quality.precision)}). La recuperación mantiene alta precisión cuando encuentra resultados.`],
    [`Persisten ${coverage.false_empty_n} vacíos falsos entre ${coverage.zero_source_consensus_n} resultados sin fuentes (${fmtPct(falseEmptyRate)}); este criterio no se cumple.`],
    [`La exactitud de postura preliminar es ${stance.accuracy_count}/${stance.n} (${fmtPct(stance.accuracy)}). Debe cerrarse la adjudicación antes de declarar el resultado final.`],
  ];
  sheet.getRange("G13:L17").format.font = bodyFont;
  sheet.getRange("G13:L17").format.wrapText = true;
  sheet.getRange("G13:L17").format.rowHeight = 48;

  const sourceSheet = addValuesSheet(workbook, "Fuentes", sourceValues);
  formatComparisonSheet(sourceSheet, sourceValues, [[2, 13], [3, 36], [5, 30], [6, 38], [7, 48], [8, 38], [12, 30], [16, 30], [23, 34]]);
  const coverageSheet = addValuesSheet(workbook, "Cobertura", coverageValues);
  formatComparisonSheet(coverageSheet, coverageValues, [[1, 13], [2, 38], [3, 38], [7, 24], [10, 30], [12, 24], [15, 30], [23, 34]]);

  const method = workbook.worksheets.add("Método");
  method.showGridLines = false;
  method.getRange("A2:F2").merge();
  method.getRange("A2").values = [["Método, criterios y límites"]];
  method.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
  method.getRange("A4:B16").values = [
    ["Elemento", "Definición"],
    ["Etapa", "Resultados previos a adjudicación. Las métricas de calidad usan únicamente filas con acuerdo exacto entre anotadores."],
    ["Fuentes de anotación", "anotador_a_prueba_integral_completado_v2.xlsx y anotador_b_prueba_integral_1_completado.xlsx."],
    ["Integridad", `Se validaron ${summary.source_pairs} identificadores de evidencia y ${summary.coverage_cases} identificadores de caso, sin duplicados ni campos obligatorios inválidos.`],
    ["Precisión de recuperación", "Proporción de fuentes evaluables y consensuadas cuya postura humana no fue unrelated."],
    ["Exactitud de postura", "Coincidencia entre la postura del sistema y la postura humana consensuada."],
    ["Cobertura útil", "Casos sufficient o partial entre casos consensuados donde existe evidencia."],
    ["Vacío falso", "El sistema devolvió cero fuentes, pero los anotadores indicaron none: sí había evidencia relevante."],
    ["Criterios registrados", "Recuperación ≥16/20; cobertura útil ≥80%; vacíos falsos ≤20%; exactitud de postura ≥75%; precisión de fuentes ≥90%."],
    ["Muestra", `Regresión sobre la misma muestra congelada de ${summary.coverage_cases} publicaciones; no estima la prevalencia natural del feed.`],
    ["X/social", "La instantánea no contiene casos de X/social; la validación de contexto de hilos y citas queda separada."],
    ["Estado", `Falta adjudicar ${sourceAgreement.needs_adjudication_n} pares de fuentes y ${coverageAgreement.needs_adjudication_n} casos de cobertura.`],
    ["Uso", "No presentar los porcentajes previos a adjudicación como estimaciones finales. Reportar intervalos y limitaciones con la métrica final."],
  ];
  method.getRange("A4:B4").format = headerFormat;
  method.getRange("A5:B16").format.font = bodyFont;
  method.getRange("A5:B16").format.verticalAlignment = "top";
  method.getRange("B5:B16").format.wrapText = true;
  method.getRange("A:A").format.columnWidth = 29;
  method.getRange("B:B").format.columnWidth = 96;
  method.getRange("A5:B16").format.rowHeight = 40;

  sheet.tabColor = "#243B53";
  method.tabColor = "#A8B5C2";
  workbook.recalculate();
  return workbook;
}

async function buildAdjudication(sourceDisagreements, coverageDisagreements) {
  const workbook = Workbook.create();
  const sourceColumns = [
    "evidence_id", "case_id", "claim", "source_name", "source_title", "evidence_excerpt", "source_url",
    "annotator_a_status", "annotator_a_stance", "annotator_a_notes",
    "annotator_b_status", "annotator_b_stance", "annotator_b_notes",
    "final_status", "final_stance", "adjudication_rationale",
  ];
  const coverageColumns = [
    "case_id", "claim", "original_source", "original_url", "returned_source_count",
    "annotator_a_coverage", "annotator_a_missing", "annotator_a_missing_url", "annotator_a_notes",
    "annotator_b_coverage", "annotator_b_missing", "annotator_b_missing_url", "annotator_b_notes",
    "final_coverage", "final_missing", "final_missing_url", "adjudication_rationale",
  ];
  const sourceValues = selectColumns(sourceDisagreements, sourceColumns);
  const coverageValues = selectColumns(coverageDisagreements, coverageColumns);
  const source = addValuesSheet(workbook, "Fuentes", sourceValues);
  const coverage = addValuesSheet(workbook, "Cobertura", coverageValues);
  formatComparisonSheet(source, sourceValues, [[2, 36], [4, 34], [5, 48], [6, 38], [9, 34], [12, 34], [15, 42]]);
  formatComparisonSheet(coverage, coverageValues, [[1, 38], [3, 38], [8, 34], [12, 34], [15, 38], [16, 42]]);
  const sourceRows = sourceValues.length;
  const coverageRows = coverageValues.length;
  source.getRange(`N2:P${sourceRows}`).format.fill = "#FFF4CC";
  source.getRange(`N2:N${sourceRows}`).dataValidation = { rule: { type: "list", values: ["evaluable", "unavailable", "insufficient_context"] } };
  source.getRange(`O2:O${sourceRows}`).dataValidation = { rule: { type: "list", values: ["supports", "refutes", "discusses", "unrelated"] } };
  coverage.getRange(`N2:Q${coverageRows}`).format.fill = "#FFF4CC";
  coverage.getRange(`N2:N${coverageRows}`).dataValidation = { rule: { type: "list", values: ["sufficient", "partial", "none", "no_evidence_found", "unable_to_assess"] } };
  coverage.getRange(`O2:O${coverageRows}`).dataValidation = { rule: { type: "list", values: ["yes", "no", "unable_to_assess"] } };

  const guide = workbook.worksheets.add("Guía");
  guide.showGridLines = false;
  guide.getRange("A2:F2").merge();
  guide.getRange("A2").values = [["Adjudicación ciega de la regresión de evidencia"]];
  guide.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
  guide.getRange("A4:B12").values = [
    ["Paso", "Instrucción"],
    [1, "Revise únicamente las filas incluidas. Son desacuerdos entre los dos anotadores."],
    [2, "Abra las URLs cuando sea necesario y aplique las mismas definiciones de la guía original."],
    [3, "Complete solo las columnas amarillas final_* y adjudication_rationale."],
    [4, "No consulte la etiqueta del sistema ni el informe antes de decidir."],
    ["Fuentes", "Defina final_status. Si es evaluable, seleccione final_stance y documente el elemento material decisivo."],
    ["Cobertura", "Seleccione final_coverage, final_missing y, si corresponde, una URL faltante representativa."],
    ["Independencia", "Un tercero es preferible. Si adjudica uno de los anotadores, debe volver a revisar la evidencia y justificar la decisión."],
    ["Entrega", "Devuelva este libro completo para calcular las métricas finales de la regresión."],
  ];
  guide.getRange("A4:B4").format = headerFormat;
  guide.getRange("A5:B12").format.font = bodyFont;
  guide.getRange("B5:B12").format.wrapText = true;
  guide.getRange("A:A").format.columnWidth = 24;
  guide.getRange("B:B").format.columnWidth = 94;
  guide.getRange("A5:B12").format.rowHeight = 42;
  source.tabColor = "#243B53";
  coverage.tabColor = "#5B7C99";
  guide.tabColor = "#A8B5C2";
  workbook.recalculate();
  return workbook;
}

async function verifyAndExport(workbook, outputPath, previews) {
  const errorCheck = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 100 },
    summary: "final formula error scan",
  });
  await fs.mkdir(previewDir, { recursive: true });
  for (const [sheetName, range, fileName] of previews) {
    const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
    await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
  }
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  await fs.writeFile(`${outputPath}.inspect.ndjson`, errorCheck.ndjson, "utf8");
  return { outputPath, errorCheck: errorCheck.ndjson };
}

const summary = JSON.parse(await fs.readFile(path.join(inputDir, "summary.json"), "utf8"));
const sourceValues = await csvValues("source_comparison.csv");
const coverageValues = await csvValues("coverage_comparison.csv");
const sourceDisagreements = await csvValues("source_disagreements.csv");
const coverageDisagreements = await csvValues("coverage_disagreements.csv");

const report = await buildReport(summary, sourceValues, coverageValues);
const adjudication = await buildAdjudication(sourceDisagreements, coverageDisagreements);
const reportPath = path.join(outputDir, "evaluacion_regresion_v2_pre_adjudicacion.xlsx");
const adjudicationPath = path.join(outputDir, "adjudicacion_regresion_v2.xlsx");
const results = [];
results.push(await verifyAndExport(report, reportPath, [
  ["Resumen", "A1:L17", "reporte_resumen.png"],
  ["Fuentes", "A1:J8", "reporte_fuentes.png"],
  ["Cobertura", "A1:J8", "reporte_cobertura.png"],
  ["Método", "A1:B16", "reporte_metodo.png"],
]));
results.push(await verifyAndExport(adjudication, adjudicationPath, [
  ["Fuentes", "A1:P8", "adjudicacion_fuentes.png"],
  ["Cobertura", "A1:Q5", "adjudicacion_cobertura.png"],
  ["Guía", "A1:F12", "adjudicacion_guia.png"],
]));
console.log(JSON.stringify(results));
