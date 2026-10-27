import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const args = process.argv.slice(2);
const valueAfter = (flag, fallback) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : fallback;
};
const inputDir = valueAfter("--input-dir", "output/evidence_end_to_end_results_2026_10_24");
const outputDir = valueAfter("--output-dir", "outputs/evidence-end-to-end-results-2026-10-24");
const previewDir = valueAfter("--preview-dir", "output/evidence_end_to_end_results_preview");
const adjudicationOnly = args.includes("--adjudication-only");
const adjudicationName = valueAfter("--adjudication-name", "adjudicacion_prueba_integral_evidencia.xlsx");
const reviewMode = valueAfter("--review-mode", "integral");

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
  sheet.getRangeByIndexes(1, 0, Math.max(rows - 1, 1), cols).format.verticalAlignment = "top";
  for (let col = 0; col < cols; col += 1) {
    sheet.getRangeByIndexes(0, col, rows, 1).format.columnWidth = 17;
  }
  return sheet;
}

function selectColumns(values, columns) {
  const header = values[0].map(String);
  const indices = columns.map((name) => {
    const index = header.indexOf(name);
    if (index < 0) throw new Error(`Missing column ${name}`);
    return index;
  });
  return [columns, ...values.slice(1).map((row) => indices.map((index) => row[index]))];
}

function formatComparisonSheet(sheet, values, wrapColumns) {
  const rows = values.length;
  for (const [columnIndex, width] of wrapColumns) {
    sheet.getRangeByIndexes(0, columnIndex, rows, 1).format.columnWidth = width;
    if (rows > 1) sheet.getRangeByIndexes(1, columnIndex, rows - 1, 1).format.wrapText = true;
  }
  if (rows > 1) sheet.getRangeByIndexes(1, 0, rows - 1, values[0].length).format.rowHeight = 54;
}

async function buildReport(summary, sourceValues, coverageValues) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Resumen");
  sheet.showGridLines = false;
  sheet.getRange("A2:F2").merge();
  sheet.getRange("A2").values = [["Evaluación integral de evidencia — resultados previos a adjudicación"]];
  sheet.getRange("A2:F2").format = {
    font: { name: fontFamily, size: 15, bold: true, color: "#172033" },
    verticalAlignment: "center",
  };
  sheet.getRange("A4:E4").values = [["Área", "Métrica", "Resultado", "Base", "Interpretación"]];
  sheet.getRange("A4:E4").format = headerFormat;
  const metricRows = [
    ["Ejecución", "Publicaciones con al menos una fuente", summary.system_run.retrieval_success_rate, `${summary.system_run.retrieval_success_n}/20`, "Cobertura automática inicial; no mide calidad."],
    ["Fuentes", "Acuerdo de evaluabilidad", summary.source_agreement.evaluability_exact, "22 pares", "Kappa=0 por prevalencia: el anotador B marcó todas como evaluables."],
    ["Fuentes", "Acuerdo de postura entre evaluables", summary.source_agreement.stance_exact_among_both_evaluable, `${summary.source_agreement.both_evaluable_n} pares`, `Kappa=${summary.source_agreement.stance_kappa_among_both_evaluable.toFixed(3)}.`],
    ["Fuentes", "Precisión de recuperación", summary.retrieval_source_quality_consensus_only.precision, `${summary.retrieval_source_quality_consensus_only.relevant_n}/${summary.retrieval_source_quality_consensus_only.evaluable_consensus_n}`, "Todas las fuentes con consenso fueron relevantes; IC amplio por muestra pequeña."],
    ["Postura", "Exactitud contra consenso", summary.system_stance_consensus_only.accuracy, `${summary.system_stance_consensus_only.accuracy_count}/${summary.system_stance_consensus_only.n}`, "Seis discrepancias del sistema en el subconjunto consensuado."],
    ["Postura", "Macro-F1 de clases observadas", summary.system_stance_consensus_only.macro_f1_observed_gold_classes, `${summary.system_stance_consensus_only.n} pares`, "Solo supports y discusses tuvieron soporte humano consensuado."],
    ["Cobertura", "Acuerdo exacto", summary.coverage_agreement.coverage_exact, "20 casos", `Kappa=${summary.coverage_agreement.coverage_kappa.toFixed(3)}; requiere adjudicación.`],
    ["Cobertura", "Casos con evidencia útil", summary.coverage_consensus_only.useful_coverage_rate, `${summary.coverage_consensus_only.useful_coverage_n}/${summary.coverage_consensus_only.evidence_exists_n}`, "Cálculo restringido a casos con consenso y evidencia existente."],
    ["Cobertura", "Vacíos falsos", summary.coverage_consensus_only.false_empty_n, `${summary.coverage_consensus_only.zero_source_consensus_n} casos sin fuentes`, "Casos sin resultados donde ambos anotadores sí identificaron evidencia."],
    ["Pendiente", "Desacuerdos de fuentes", summary.source_agreement.needs_adjudication_n, "22 pares", "No se incluyeron en las métricas de postura del sistema."],
    ["Pendiente", "Desacuerdos de cobertura", summary.coverage_agreement.needs_adjudication_n, "20 casos", "La conclusión final depende de adjudicación humana."],
  ];
  sheet.getRange("A5").write(metricRows);
  sheet.getRange("A5:E15").format.font = bodyFont;
  sheet.getRange("A5:E15").format.verticalAlignment = "top";
  sheet.getRange("B5:B15").format.wrapText = true;
  sheet.getRange("E5:E15").format.wrapText = true;
  for (const row of [5, 6, 7, 8, 9, 10, 11, 12]) sheet.getRange(`C${row}`).format.numberFormat = "0.0%";
  sheet.getRange("A:A").format.columnWidth = 15;
  sheet.getRange("B:B").format.columnWidth = 36;
  sheet.getRange("C:C").format.columnWidth = 16;
  sheet.getRange("D:D").format.columnWidth = 20;
  sheet.getRange("E:E").format.columnWidth = 62;
  sheet.getRange("A5:A15").format.fill = "#EEF3F7";
  sheet.getRange("A5:E15").format.rowHeight = 34;

  sheet.getRange("G4:I4").merge();
  sheet.getRange("G4").values = [["Matriz de confusión de postura (consenso)"]];
  sheet.getRange("G4:I4").format = sectionFormat;
  sheet.getRange("G5:I8").values = [
    ["Humano / sistema", "supports", "discusses"],
    ["supports", 7, 4],
    ["discusses", 2, 5],
    ["Total", 9, 9],
  ];
  sheet.getRange("G5:I5").format = headerFormat;
  sheet.getRange("G6:I8").format.font = bodyFont;
  sheet.getRange("G:G").format.columnWidth = 24;
  sheet.getRange("H:I").format.columnWidth = 16;

  sheet.getRange("G11:K11").merge();
  sheet.getRange("G11").values = [["Lectura defendible"]];
  sheet.getRange("G11:K11").format = sectionFormat;
  sheet.getRange("G12:K16").merge(true);
  sheet.getRange("G12:G16").values = [
    ["La selección fue precisa cuando devolvió evidencia: 18/18 fuentes consensuadas fueron relevantes."],
    ["La cobertura es el principal problema: el sistema dejó 9/20 publicaciones sin fuentes y hubo cuatro vacíos falsos entre los cinco casos vacíos con consenso."],
    ["La postura bajó a 66.7% de exactitud en el flujo integral; los errores se concentraron en la frontera supports/discusses."],
    ["El acuerdo de cobertura fue bajo (50.0%, κ=0.310), así que no corresponde cerrar conclusiones sin adjudicar diez casos."],
    ["Este piloto es estratificado, pequeño, sin casos de X y sin umbral de aprobación preregistrado."],
  ];
  sheet.getRange("G12:K16").format.font = bodyFont;
  sheet.getRange("G12:K16").format.wrapText = true;
  sheet.getRange("G12:K16").format.rowHeight = 44;
  sheet.getRange("G:G").format.columnWidth = 32;

  const sourceSheet = addValuesSheet(workbook, "Fuentes", sourceValues);
  formatComparisonSheet(sourceSheet, sourceValues, [[2, 13], [3, 36], [5, 30], [6, 38], [7, 48], [8, 38], [12, 30], [16, 30], [23, 34]]);
  const coverageSheet = addValuesSheet(workbook, "Cobertura", coverageValues);
  formatComparisonSheet(coverageSheet, coverageValues, [[1, 13], [2, 38], [3, 38], [7, 24], [10, 30], [12, 24], [15, 30], [23, 34]]);

  const method = workbook.worksheets.add("Método");
  method.showGridLines = false;
  method.getRange("A2:F2").merge();
  method.getRange("A2").values = [["Método y límites"]];
  method.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
  method.getRange("A4:B15").values = [
    ["Elemento", "Definición"],
    ["Etapa", "Resultados previos a adjudicación. Las métricas del sistema usan únicamente filas con acuerdo exacto."],
    ["Precisión de recuperación", "Proporción de fuentes evaluables y consensuadas cuya postura humana no fue unrelated."],
    ["Exactitud de postura", "Coincidencia entre evidence-policy-2026-10-22-v3 y la postura humana consensuada."],
    ["Cobertura útil", "Casos sufficient o partial entre casos consensuados donde existe evidencia."],
    ["Vacío falso", "El sistema devolvió cero fuentes, pero ambos anotadores indicaron none: sí había evidencia relevante."],
    ["Evaluabilidad", "Kappa es 0 porque un anotador no usó la categoría no evaluable; el acuerdo bruto de 86.4% sigue siendo informativo."],
    ["Macro-F1", "Se reporta la media de las clases observadas. La media fija de cuatro clases es 0.331 porque refutes y unrelated no tuvieron soporte."],
    ["Muestra", "20 publicaciones estratificadas; 22 fuentes recuperadas. No representa la prevalencia natural del feed."],
    ["X/social", "No hubo publicaciones sociales en la instantánea de producción."],
    ["Umbral", "No se preregistró un criterio de aprobación; el estudio es un piloto integral."],
    ["Siguiente paso", "Adjudicar 4 pares de fuentes y 10 casos de cobertura sin consultar la etiqueta del sistema."],
  ];
  method.getRange("A4:B4").format = headerFormat;
  method.getRange("A5:B15").format.font = bodyFont;
  method.getRange("A5:B15").format.verticalAlignment = "top";
  method.getRange("B5:B15").format.wrapText = true;
  method.getRange("A:A").format.columnWidth = 28;
  method.getRange("B:B").format.columnWidth = 92;
  method.getRange("A5:B15").format.rowHeight = 38;

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
    "case_id", "claim", "publication_context", "original_source", "original_url", "returned_source_count",
    "annotator_a_coverage", "annotator_a_missing", "annotator_a_missing_url", "annotator_a_notes",
    "annotator_b_coverage", "annotator_b_missing", "annotator_b_missing_url", "annotator_b_notes",
    "final_coverage", "final_missing", "final_missing_url", "adjudication_rationale",
  ];
  const sourceValues = selectColumns(sourceDisagreements, sourceColumns);
  const coverageValues = selectColumns(coverageDisagreements, coverageColumns);
  const source = addValuesSheet(workbook, "Fuentes", sourceValues);
  const coverage = addValuesSheet(workbook, "Cobertura", coverageValues);
  formatComparisonSheet(source, sourceValues, [[2, 36], [4, 34], [5, 48], [6, 38], [9, 34], [12, 34], [15, 40]]);
  formatComparisonSheet(coverage, coverageValues, [[1, 38], [2, 72], [4, 38], [9, 34], [13, 34], [16, 38], [17, 40]]);
  const sourceRows = sourceValues.length;
  const coverageRows = coverageValues.length;
  if (reviewMode === "focused-v5") {
    if (sourceRows > 1) source.getRange(`A2:P${sourceRows}`).format.rowHeight = 120;
    if (coverageRows > 1) coverage.getRange(`A2:R${coverageRows}`).format.rowHeight = 180;
  }
  source.getRange(`N2:P${sourceRows}`).format.fill = "#FFF4CC";
  source.getRange(`N2:N${sourceRows}`).dataValidation = { rule: { type: "list", values: ["evaluable", "unavailable", "insufficient_context"] } };
  source.getRange(`O2:O${sourceRows}`).dataValidation = { rule: { type: "list", values: ["supports", "refutes", "discusses", "unrelated"] } };
  coverage.getRange(`O2:R${coverageRows}`).format.fill = "#FFF4CC";
  coverage.getRange(`O2:O${coverageRows}`).dataValidation = { rule: { type: "list", values: ["sufficient", "partial", "none", "no_evidence_found", "unable_to_assess"] } };
  coverage.getRange(`P2:P${coverageRows}`).dataValidation = { rule: { type: "list", values: ["yes", "no", "unable_to_assess"] } };

  const guide = workbook.worksheets.add("Guía");
  guide.showGridLines = false;
  guide.getRange("A2:F2").merge();
  guide.getRange("A2").values = [[reviewMode === "focused-v5"
    ? "Adjudicación ciega focalizada v5"
    : "Adjudicación ciega de la prueba integral"]];
  guide.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
  const guideRows = [
    ["Paso", "Instrucción"],
    [1, "Revise únicamente las filas incluidas. Son desacuerdos entre los dos anotadores."],
    [2, "Abra las URLs cuando sea necesario y aplique las mismas definiciones de la guía original."],
    [3, "Complete solo las columnas amarillas final_* y adjudication_rationale."],
    [4, "No consulte la etiqueta del sistema ni los resultados del informe antes de decidir."],
    ["Fuentes", "Defina primero final_status. Si es evaluable, seleccione final_stance y explique brevemente el elemento material decisivo."],
    ["Cobertura", "Seleccione final_coverage, final_missing y, si corresponde, una URL faltante representativa."],
    ...(reviewMode === "focused-v5" ? [["Contexto primario", "Una fuente marcada primary_context sirve para comprender la publicación, pero no cuenta como corroboración independiente. Aun así, puede hacer suficiente un caso que solo reproduce una declaración original si la tarea es evaluar esa declaración y no exige corroboración externa."]] : []),
    ["Independencia", "La persona adjudicadora puede ser uno de los anotadores solo si vuelve a revisar la evidencia y documenta la razón; un tercero es preferible."],
    ["Entrega", "Devuelva este libro completo para calcular las métricas finales."],
  ];
  const guideLastRow = 3 + guideRows.length;
  guide.getRange(`A4:B${guideLastRow}`).values = guideRows;
  guide.getRange("A4:B4").format = headerFormat;
  guide.getRange(`A5:B${guideLastRow}`).format.font = bodyFont;
  guide.getRange(`B5:B${guideLastRow}`).format.wrapText = true;
  guide.getRange("A:A").format.columnWidth = 24;
  guide.getRange("B:B").format.columnWidth = 92;
  guide.getRange(`A5:B${guideLastRow}`).format.rowHeight = 48;
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

const adjudication = await buildAdjudication(sourceDisagreements, coverageDisagreements);
const reportPath = path.join(outputDir, "evaluacion_integral_evidencia_pre_adjudicacion.xlsx");
const adjudicationPath = path.join(outputDir, adjudicationName);
const results = [];
if (!adjudicationOnly) {
  const report = await buildReport(summary, sourceValues, coverageValues);
  results.push(await verifyAndExport(report, reportPath, [
    ["Resumen", "A1:K16", "reporte_resumen.png"],
    ["Fuentes", "A1:J6", "reporte_fuentes.png"],
    ["Cobertura", "A1:J6", "reporte_cobertura.png"],
    ["Método", "A1:B15", "reporte_metodo.png"],
  ]));
}
results.push(await verifyAndExport(adjudication, adjudicationPath, [
  ["Fuentes", "A1:P2", "adjudicacion_fuentes.png"],
  ["Cobertura", "A1:R6", "adjudicacion_cobertura.png"],
  ["Guía", "A1:F13", "adjudicacion_guia.png"],
]));
console.log(JSON.stringify(results));
