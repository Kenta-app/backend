import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const args = process.argv.slice(2);
const valueAfter = (flag, fallback) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : fallback;
};

const inputDir = valueAfter("--input-dir", "output/evidence_end_to_end_regression_v2_final_2026_10_25");
const baselinePath = valueAfter("--baseline-summary", "output/evidence_end_to_end_final_2026_10_25/final_summary.json");
const outputPath = valueAfter("--output", "outputs/evidence-retrieval-regression-v2-final-2026-10-25/evaluacion_regresion_v2_final.xlsx");
const previewDir = valueAfter("--preview-dir", "output/evidence_retrieval_regression_v2_final_preview");

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
  verticalAlignment: "center",
};

async function csvValues(fileName, sheetName = "Data") {
  const csvText = (await fs.readFile(path.join(inputDir, fileName), "utf8")).replace(/^\uFEFF/, "");
  const temp = await Workbook.fromCSV(csvText, { sheetName });
  return temp.worksheets.getItem(sheetName).getUsedRange(true).values;
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

function addDataSheet(workbook, name, values, widths, wrapColumns = []) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  sheet.getRange("A1").write(values);
  const rows = values.length;
  const cols = values[0].length;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
  sheet.getRangeByIndexes(0, 0, rows, cols).format.font = bodyFont;
  sheet.getRangeByIndexes(0, 0, 1, cols).format = headerFormat;
  sheet.getRangeByIndexes(0, 0, 1, cols).format.rowHeight = 42;
  if (rows > 1) {
    sheet.getRangeByIndexes(1, 0, rows - 1, cols).format.verticalAlignment = "top";
    sheet.getRangeByIndexes(1, 0, rows - 1, cols).format.rowHeight = 58;
  }
  widths.forEach((width, index) => sheet.getRangeByIndexes(0, index, rows, 1).format.columnWidth = width);
  wrapColumns.forEach((index) => {
    if (rows > 1) sheet.getRangeByIndexes(1, index, rows - 1, 1).format.wrapText = true;
  });
  return sheet;
}

function pct(value) {
  return typeof value === "number" ? value : Number(value);
}

function percentText(value) {
  return `${(100 * value).toFixed(1)}%`;
}

function intervalText(interval) {
  return `${percentText(interval[0])}–${percentText(interval[1])}`;
}

const summary = JSON.parse(await fs.readFile(path.join(inputDir, "final_summary.json"), "utf8"));
const baseline = JSON.parse(await fs.readFile(baselinePath, "utf8"));
const sourceRaw = await csvValues("final_source_results.csv");
const coverageRaw = await csvValues("final_coverage_results.csv");
const auditRaw = await csvValues("adjudication_audit.csv");

const sourceValues = selectColumns(sourceRaw, [
  "evidence_id", "case_id", "claim", "source_name", "source_title", "source_url",
  "model_stance", "annotator_a_stance", "annotator_b_stance", "final_status",
  "final_stance", "model_matches_final", "decision_source", "adjudication_rationale",
]);
const coverageValues = selectColumns(coverageRaw, [
  "case_id", "claim", "original_source", "original_url", "returned_source_count",
  "annotator_a_coverage", "annotator_b_coverage", "final_coverage", "final_missing",
  "final_missing_url", "decision_source", "adjudication_rationale",
]);

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Resumen");
sheet.showGridLines = false;
sheet.getRange("A2:F2").merge();
sheet.getRange("A2").values = [["Regresión de recuperación de evidencia — resultados finales adjudicados"]];
sheet.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };

sheet.getRange("A4:F4").values = [["Criterio registrado", "Umbral", "Resultado final", "Base", "Estado", "Lectura"]];
sheet.getRange("A4:F4").format = headerFormat;
const criteria = summary.registered_criteria;
const criteriaRows = [
  ["Publicaciones con fuentes", "≥16/20", summary.system_run.retrieval_success_rate, `${summary.system_run.retrieval_success_n}/${summary.coverage_cases}`, criteria.retrieval_at_least_16_of_20.passed ? "Cumple" : "No cumple", "La búsqueda recuperó evidencia en 85% de la muestra."],
  ["Cobertura útil", "≥80%", summary.coverage_final.useful_coverage_rate, `${summary.coverage_final.useful_coverage_n}/${summary.coverage_final.evidence_exists_n}`, criteria.useful_coverage_at_least_80_percent.passed ? "Cumple" : "No cumple", "Incluye sufficient y partial entre casos donde existe evidencia."],
  ["Vacíos falsos", "≤20%", summary.false_empty_rate, `${summary.coverage_final.false_empty_n}/${summary.coverage_final.zero_source_n}`, criteria.false_empty_rate_at_most_20_percent.passed ? "Cumple" : "No cumple", "Dos de los tres resultados vacíos omitieron evidencia existente."],
  ["Exactitud de postura", "≥75%", summary.system_stance_final.accuracy, `${summary.system_stance_final.accuracy_count}/${summary.system_stance_final.n}`, criteria.stance_accuracy_at_least_75_percent.passed ? "Cumple" : "No cumple", "Los errores se concentran en supports/discusses y en los dos casos refutes."],
  ["Precisión de fuentes", "≥90%", summary.retrieval_source_quality_final.precision, `${summary.retrieval_source_quality_final.relevant_n}/${summary.retrieval_source_quality_final.evaluable_n}`, criteria.source_precision_at_least_90_percent.passed ? "Cumple" : "No cumple", `IC95% de Wilson: ${intervalText(summary.retrieval_source_quality_final.precision_wilson_95)}.`],
];
sheet.getRange("A5").write(criteriaRows);
sheet.getRange("A5:F9").format.font = bodyFont;
sheet.getRange("A5:F9").format.verticalAlignment = "top";
sheet.getRange("A5:A9").format.fill = "#EEF3F7";
sheet.getRange("F5:F9").format.wrapText = true;
sheet.getRange("C5:C9").format.numberFormat = "0.0%";
sheet.getRange("A5:F9").format.rowHeight = 40;
sheet.getRange("E5:E9").conditionalFormats.add("containsText", { text: "No cumple", format: { fill: "#FDECEC", font: { bold: true, color: "#A61B1B" } } });
sheet.getRange("A:A").format.columnWidth = 32;
sheet.getRange("B:B").format.columnWidth = 16;
sheet.getRange("C:C").format.columnWidth = 18;
sheet.getRange("D:D").format.columnWidth = 16;
sheet.getRange("E:E").format.columnWidth = 16;
sheet.getRange("F:F").format.columnWidth = 64;

sheet.getRange("A12:F12").merge();
sheet.getRange("A12").values = [["Comparación con el piloto inicial"]];
sheet.getRange("A12:F12").format = sectionFormat;
sheet.getRange("A13:D19").values = [
  ["Métrica", "Piloto inicial", "Regresión final", "Cambio"],
  ["Publicaciones con fuentes", baseline.system_run.retrieval_success_rate, summary.system_run.retrieval_success_rate, summary.system_run.retrieval_success_rate - baseline.system_run.retrieval_success_rate],
  ["Precisión de fuentes", baseline.retrieval_source_quality_final.precision, summary.retrieval_source_quality_final.precision, summary.retrieval_source_quality_final.precision - baseline.retrieval_source_quality_final.precision],
  ["Exactitud de postura", baseline.system_stance_final.accuracy, summary.system_stance_final.accuracy, summary.system_stance_final.accuracy - baseline.system_stance_final.accuracy],
  ["Cobertura útil", baseline.coverage_final.useful_coverage_rate, summary.coverage_final.useful_coverage_rate, summary.coverage_final.useful_coverage_rate - baseline.coverage_final.useful_coverage_rate],
  ["Cobertura suficiente", baseline.coverage_final.sufficient_coverage_rate, summary.coverage_final.sufficient_coverage_rate, summary.coverage_final.sufficient_coverage_rate - baseline.coverage_final.sufficient_coverage_rate],
  ["Tasa de vacíos falsos", baseline.coverage_final.false_empty_n / baseline.coverage_final.zero_source_n, summary.false_empty_rate, summary.false_empty_rate - baseline.coverage_final.false_empty_n / baseline.coverage_final.zero_source_n],
];
sheet.getRange("A13:D13").format = headerFormat;
sheet.getRange("A14:D19").format.font = bodyFont;
sheet.getRange("B14:D19").format.numberFormat = "0.0%";
sheet.getRange("A14:A19").format.fill = "#EEF3F7";
sheet.getRange("A14:D19").format.rowHeight = 30;

sheet.getRange("H4:M4").merge();
sheet.getRange("H4").values = [["Matriz de confusión final: postura humana × modelo"]];
sheet.getRange("H4:M4").format = sectionFormat;
const cm = summary.system_stance_final.confusion_matrix_gold_by_model;
sheet.getRange("H5:M10").values = [
  ["Humano / modelo", "supports", "refutes", "discusses", "unrelated", "Total"],
  ["supports", cm.supports.supports, cm.supports.refutes, cm.supports.discusses, cm.supports.unrelated, Object.values(cm.supports).reduce((a, b) => a + b, 0)],
  ["refutes", cm.refutes.supports, cm.refutes.refutes, cm.refutes.discusses, cm.refutes.unrelated, Object.values(cm.refutes).reduce((a, b) => a + b, 0)],
  ["discusses", cm.discusses.supports, cm.discusses.refutes, cm.discusses.discusses, cm.discusses.unrelated, Object.values(cm.discusses).reduce((a, b) => a + b, 0)],
  ["unrelated", cm.unrelated.supports, cm.unrelated.refutes, cm.unrelated.discusses, cm.unrelated.unrelated, Object.values(cm.unrelated).reduce((a, b) => a + b, 0)],
  ["Total", 14, 0, 15, 0, summary.system_stance_final.n],
];
sheet.getRange("H5:M5").format = headerFormat;
sheet.getRange("H6:M10").format.font = bodyFont;
sheet.getRange("H6:H10").format.fill = "#EEF3F7";
sheet.getRange("H:H").format.columnWidth = 24;
sheet.getRange("I:M").format.columnWidth = 14;

sheet.getRange("H12:M12").merge();
sheet.getRange("H12").values = [["Conclusión defendible"]];
sheet.getRange("H12:M12").format = sectionFormat;
sheet.getRange("H13:M19").merge(true);
sheet.getRange("H13:H19").values = [
  ["La regresión cumple 3 de los 5 criterios registrados. No corresponde declarar que el módulo superó la validación completa."],
  [`La recuperación mejoró de 11/20 a 17/20 publicaciones y la cobertura útil de ${percentText(baseline.coverage_final.useful_coverage_rate)} a ${percentText(summary.coverage_final.useful_coverage_rate)}.`],
  [`Las 29 fuentes evaluables fueron relevantes (${percentText(summary.retrieval_source_quality_final.precision)}; IC95% ${intervalText(summary.retrieval_source_quality_final.precision_wilson_95)}).`],
  [`La exactitud de postura fue ${summary.system_stance_final.accuracy_count}/${summary.system_stance_final.n} (${percentText(summary.system_stance_final.accuracy)}; IC95% ${intervalText(summary.system_stance_final.accuracy_wilson_95)}), por debajo del 75%.`],
  [`La tasa de vacíos falsos bajó, pero sigue en ${percentText(summary.false_empty_rate)} y excede ampliamente el máximo de 20%.`],
  ["La siguiente mejora debe priorizar la recuperación de los dos vacíos persistentes y la calibración de supports/discusses/refutes."],
  ["Esta es una prueba de regresión sobre la muestra congelada. Una muestra nueva y ciega sigue siendo necesaria para confirmación."],
];
sheet.getRange("H13:M19").format.font = bodyFont;
sheet.getRange("H13:M19").format.wrapText = true;
sheet.getRange("H13:M19").format.rowHeight = 45;

const sourceSheet = addDataSheet(workbook, "Fuentes", sourceValues,
  [17, 14, 42, 22, 42, 38, 16, 18, 18, 16, 16, 18, 18, 52], [2, 4, 5, 13]);
const coverageSheet = addDataSheet(workbook, "Cobertura", coverageValues,
  [15, 44, 22, 38, 17, 22, 22, 20, 18, 42, 18, 52], [1, 3, 9, 11]);
const auditSheet = addDataSheet(workbook, "Adjudicación", auditRaw,
  [16, 18, 15, 31, 31, 31, 72], [3, 4, 5, 6]);

const method = workbook.worksheets.add("Método");
method.showGridLines = false;
method.getRange("A2:F2").merge();
method.getRange("A2").values = [["Método, criterios y límites"]];
method.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
method.getRange("A4:B17").values = [
  ["Elemento", "Definición"],
  ["Etapa", "Resultados finales de la regresión. Las filas con acuerdo exacto conservan el consenso y los desacuerdos usan decisión adjudicada y justificada."],
  ["Fuente de adjudicación", "evaluacion_regresion_v2_adjudicada.xlsx."],
  ["Unidades", `${summary.source_pairs} pares afirmación–fuente y ${summary.coverage_cases} publicaciones; ${summary.adjudicated_source_n} fuentes y ${summary.adjudicated_coverage_n} casos fueron adjudicados.`],
  ["Precisión de fuentes", "Proporción de fuentes evaluables cuya postura final no fue unrelated."],
  ["Exactitud de postura", "Coincidencia entre la etiqueta del sistema y la postura humana final."],
  ["Cobertura útil", "Casos sufficient o partial entre aquellos donde la revisión humana estableció que existía evidencia."],
  ["Vacío falso", "El sistema devolvió cero fuentes, pero la revisión estableció que sí existía evidencia relevante."],
  ["Criterios registrados", "Recuperación ≥16/20; cobertura útil ≥80%; vacíos falsos ≤20%; exactitud de postura ≥75%; precisión de fuentes ≥90%."],
  ["Registro temporal", "Los criterios se fijaron después del piloto inicial y antes de ejecutar esta regresión."],
  ["Acuerdo", "Las métricas de acuerdo se calculan antes de adjudicar; no son métricas de desempeño del sistema."],
  ["Muestra", "La regresión reutiliza la muestra estratificada congelada. No estima la prevalencia natural del feed."],
  ["X/social", "La instantánea no contiene publicaciones de X; la validación de hilos, respuestas y quotes requiere una prueba dedicada."],
  ["Confirmación", "Una muestra nueva y ciega es necesaria para estimar desempeño confirmatorio y evitar sobreajuste a esta muestra."],
];
method.getRange("A4:B4").format = headerFormat;
method.getRange("A5:B17").format.font = bodyFont;
method.getRange("A5:B17").format.verticalAlignment = "top";
method.getRange("B5:B17").format.wrapText = true;
method.getRange("A:A").format.columnWidth = 29;
method.getRange("B:B").format.columnWidth = 100;
method.getRange("A5:B17").format.rowHeight = 42;

sheet.tabColor = "#243B53";
sourceSheet.tabColor = "#5B7C99";
coverageSheet.tabColor = "#5B7C99";
auditSheet.tabColor = "#A67C00";
method.tabColor = "#A8B5C2";
workbook.recalculate();

const summaryCheck = await workbook.inspect({ kind: "table", range: "Resumen!A4:M19", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 13, maxChars: 12000 });
const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

await fs.mkdir(previewDir, { recursive: true });
const previews = [
  ["Resumen", "A1:M19", "resumen.png"],
  ["Fuentes", "A1:N8", "fuentes.png"],
  ["Cobertura", "A1:L8", "cobertura.png"],
  ["Adjudicación", `A1:G${auditRaw.length}`, "adjudicacion.png"],
  ["Método", "A1:B17", "metodo.png"],
];
for (const [sheetName, range, fileName] of previews) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(`${outputPath}.inspect.ndjson`, `${summaryCheck.ndjson}\n${errorCheck.ndjson}`, "utf8");
console.log(JSON.stringify({ outputPath, previewDir, errorCheck: errorCheck.ndjson }, null, 2));
