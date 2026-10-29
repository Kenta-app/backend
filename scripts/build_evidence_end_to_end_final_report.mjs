import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const args = process.argv.slice(2);
const valueAfter = (flag, fallback) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : fallback;
};
const inputDir = valueAfter("--input-dir", "output/evidence_end_to_end_final_2026_10_25");
const outputPath = valueAfter(
  "--output",
  "outputs/evidence-end-to-end-final-2026-10-25/evaluacion_integral_evidencia_final.xlsx",
);
const previewDir = valueAfter("--preview-dir", "output/evidence_end_to_end_final_preview");
const reviewMode = valueAfter("--review-mode", "integral");
const confirmatoryV7 = reviewMode === "confirmatory-v7";

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
    sheet.getRangeByIndexes(1, 0, rows - 1, cols).format.rowHeight = 54;
  }
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rows, 1).format.columnWidth = width;
  });
  wrapColumns.forEach((index) => {
    if (rows > 1) sheet.getRangeByIndexes(1, index, rows - 1, 1).format.wrapText = true;
  });
  return sheet;
}

function pct(value) {
  return typeof value === "number" ? value : Number(value);
}

const summary = JSON.parse(await fs.readFile(path.join(inputDir, "final_summary.json"), "utf8"));
const sourceRaw = await csvValues("final_source_results.csv");
const coverageRaw = await csvValues("final_coverage_results.csv");
const auditRaw = await csvValues("adjudication_audit.csv");

const sourceValues = selectColumns(sourceRaw, [
  "evidence_id", "case_id", "claim", "source_name", "source_title", "source_url",
  "model_stance", "annotator_a_status", "annotator_a_stance", "annotator_b_status",
  "annotator_b_stance", "final_status", "final_stance", "model_matches_final",
  "decision_source", "adjudication_rationale",
]);
const coverageValues = selectColumns(coverageRaw, confirmatoryV7 ? [
  "case_id", "platform", "claim", "publication_context", "original_source", "original_url", "returned_source_count",
  "annotator_a_coverage", "annotator_b_coverage", "final_coverage", "final_missing", "final_missing_url",
  "final_social_context", "decision_source", "adjudication_rationale",
] : [
  "case_id", "claim", "original_source", "original_url", "returned_source_count",
  "annotator_a_coverage", "annotator_b_coverage", "final_coverage", "final_missing",
  "final_missing_url", "decision_source", "adjudication_rationale",
]);

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Resumen");
sheet.showGridLines = false;
sheet.getRange("A2:F2").merge();
sheet.getRange("A2").values = [[confirmatoryV7
  ? "Evaluación confirmatoria final v7 — resultados adjudicados"
  : "Evaluación integral de evidencia — resultados finales adjudicados"]];
sheet.getRange("A2:F2").format = {
  font: { name: fontFamily, size: 15, bold: true, color: "#172033" },
  verticalAlignment: "center",
};
sheet.getRange("A4:E4").values = [["Área", "Métrica", "Resultado", "Base", "Lectura"]];
sheet.getRange("A4:E4").format = headerFormat;
const metricRows = confirmatoryV7 ? [
  ["Ejecución", "Publicaciones con al menos una fuente", pct(summary.system_run.retrieval_success_rate), `${summary.system_run.retrieval_success_n}/${summary.coverage_cases}`, "Supera el umbral prerregistrado de 80%."],
  ["Fuentes", "Precisión de fuentes recuperadas", pct(summary.retrieval_source_quality_final.precision), `${summary.retrieval_source_quality_final.relevant_n}/${summary.retrieval_source_quality_final.evaluable_n}`, "Todas las fuentes evaluables fueron relevantes."],
  ["Postura", "Exactitud final", pct(summary.system_stance_final.accuracy), `${summary.system_stance_final.accuracy_count}/${summary.system_stance_final.n}`, "No alcanza el umbral prerregistrado de 75%."],
  ["Postura", "Macro-F1 (clases observadas)", pct(summary.system_stance_final.macro_f1_observed_gold_classes), `${summary.system_stance_final.n} fuentes`, "El gold final contiene supports y discusses."],
  ["Cobertura", "Cobertura útil cuando existe evidencia", pct(summary.coverage_final.useful_coverage_rate), `${summary.coverage_final.useful_coverage_n}/${summary.coverage_final.evidence_exists_n}`, "Supera el umbral prerregistrado de 80%."],
  ["Cobertura", "Cobertura suficiente cuando existe evidencia", pct(summary.coverage_final.sufficient_coverage_rate), `${summary.coverage_final.sufficient_coverage_n}/${summary.coverage_final.evidence_exists_n}`, "Solo un caso quedó como partial."],
  ["Cobertura", "Vacíos falsos", summary.coverage_final.false_empty_n, `${summary.coverage_final.zero_source_n} casos sin fuentes`, "No se adjudicaron conjuntos vacíos como none."],
  ["Cobertura", "Casos con fuente importante omitida", summary.coverage_final.missing_yes_n, `${summary.coverage_cases} casos`, "La omisión corresponde al caso C7-007."],
  ["Contexto social", "Interpretación correcta", pct(summary.social_context_final.correct_rate), `${summary.social_context_final.correct_n}/${summary.social_context_final.social_cases_n}`, "Los seis casos de X fueron correctos."],
  ["Acuerdo", "Postura: acuerdo exacto pre-adjudicación", pct(summary.interannotator_agreement_pre_adjudication.source_agreement.stance_exact_among_both_evaluable), `${summary.interannotator_agreement_pre_adjudication.source_agreement.both_evaluable_n} fuentes`, `κ=${summary.interannotator_agreement_pre_adjudication.source_agreement.stance_kappa_among_both_evaluable.toFixed(3)}.`],
  ["Acuerdo", "Cobertura: acuerdo exacto pre-adjudicación", pct(summary.interannotator_agreement_pre_adjudication.coverage_agreement.coverage_exact), `${summary.coverage_cases} casos`, `κ=${summary.interannotator_agreement_pre_adjudication.coverage_agreement.coverage_kappa.toFixed(3)}.`],
] : [
  ["Ejecución", "Publicaciones con al menos una fuente", pct(summary.system_run.retrieval_success_rate), `${summary.system_run.retrieval_success_n}/${summary.coverage_cases}`, "La recuperación devolvió evidencia en poco más de la mitad de la muestra."],
  ["Fuentes", "Precisión de fuentes recuperadas", pct(summary.retrieval_source_quality_final.precision), `${summary.retrieval_source_quality_final.relevant_n}/${summary.retrieval_source_quality_final.evaluable_n}`, "Las fuentes recuperadas fueron pertinentes para la afirmación; el IC sigue siendo amplio."],
  ["Postura", "Exactitud final", pct(summary.system_stance_final.accuracy), `${summary.system_stance_final.accuracy_count}/${summary.system_stance_final.n}`, "Los errores se concentran en distinguir supports de discusses."],
  ["Postura", "Macro-F1 (clases observadas)", pct(summary.system_stance_final.macro_f1_observed_gold_classes), `${summary.system_stance_final.n} fuentes`, "Solo supports y discusses tuvieron ejemplos adjudicados."],
  ["Cobertura", "Cobertura útil cuando existe evidencia", pct(summary.coverage_final.useful_coverage_rate), `${summary.coverage_final.useful_coverage_n}/${summary.coverage_final.evidence_exists_n}`, "Suma casos sufficient y partial; muestra margen importante de mejora en exhaustividad."],
  ["Cobertura", "Cobertura suficiente cuando existe evidencia", pct(summary.coverage_final.sufficient_coverage_rate), `${summary.coverage_final.sufficient_coverage_n}/${summary.coverage_final.evidence_exists_n}`, "Solo siete casos reunieron evidencia suficiente."],
  ["Cobertura", "Vacíos falsos", summary.coverage_final.false_empty_n, `${summary.coverage_final.zero_source_n} casos sin fuentes`, "En ocho casos sin resultados sí existía evidencia relevante."],
  ["Cobertura", "Casos con fuente importante omitida", summary.coverage_final.missing_yes_n, `${summary.coverage_cases} casos`, "La omisión fue confirmada en doce casos."],
  ["Acuerdo", "Postura: acuerdo exacto pre-adjudicación", pct(summary.interannotator_agreement_pre_adjudication.source_agreement.stance_exact_among_both_evaluable), `${summary.interannotator_agreement_pre_adjudication.source_agreement.both_evaluable_n} fuentes`, `κ=${summary.interannotator_agreement_pre_adjudication.source_agreement.stance_kappa_among_both_evaluable.toFixed(3)}.`],
  ["Acuerdo", "Cobertura: acuerdo exacto pre-adjudicación", pct(summary.interannotator_agreement_pre_adjudication.coverage_agreement.coverage_exact), `${summary.coverage_cases} casos`, `κ=${summary.interannotator_agreement_pre_adjudication.coverage_agreement.coverage_kappa.toFixed(3)}; criterio más subjetivo.`],
];
sheet.getRange("A5").write(metricRows);
const metricLastRow = 4 + metricRows.length;
sheet.getRange(`A5:E${metricLastRow}`).format.font = bodyFont;
sheet.getRange(`A5:E${metricLastRow}`).format.verticalAlignment = "top";
sheet.getRange(`A5:A${metricLastRow}`).format.fill = "#EEF3F7";
sheet.getRange(`B5:B${metricLastRow}`).format.wrapText = true;
sheet.getRange(`E5:E${metricLastRow}`).format.wrapText = true;
(confirmatoryV7 ? [5, 6, 7, 8, 9, 10, 13, 14, 15] : [5, 6, 7, 8, 9, 10, 13, 14])
  .forEach((row) => sheet.getRange(`C${row}`).format.numberFormat = "0.0%");
sheet.getRange(`A5:E${metricLastRow}`).format.rowHeight = 38;
sheet.getRange("A:A").format.columnWidth = 15;
sheet.getRange("B:B").format.columnWidth = 39;
sheet.getRange("C:C").format.columnWidth = 16;
sheet.getRange("D:D").format.columnWidth = 22;
sheet.getRange("E:E").format.columnWidth = 61;

sheet.getRange("G4:K4").merge();
sheet.getRange("G4").values = [["Matriz de confusión final — postura humana × modelo"]];
sheet.getRange("G4:K4").format = sectionFormat;
const cm = summary.system_stance_final.confusion_matrix_gold_by_model;
sheet.getRange("G5:K9").values = [
  ["Humano / modelo", "supports", "refutes", "discusses", "unrelated"],
  ["supports", cm.supports.supports, cm.supports.refutes, cm.supports.discusses, cm.supports.unrelated],
  ["refutes", cm.refutes.supports, cm.refutes.refutes, cm.refutes.discusses, cm.refutes.unrelated],
  ["discusses", cm.discusses.supports, cm.discusses.refutes, cm.discusses.discusses, cm.discusses.unrelated],
  ["unrelated", cm.unrelated.supports, cm.unrelated.refutes, cm.unrelated.discusses, cm.unrelated.unrelated],
];
sheet.getRange("G5:K5").format = headerFormat;
sheet.getRange("G6:K9").format.font = bodyFont;
sheet.getRange("G6:G9").format.fill = "#EEF3F7";
sheet.getRange("G:G").format.columnWidth = 24;
sheet.getRange("H:K").format.columnWidth = 14;

sheet.getRange("G11:K11").merge();
sheet.getRange("G11").values = [["Conclusión defendible"]];
sheet.getRange("G11:K11").format = sectionFormat;
sheet.getRange("G12:K17").merge(true);
sheet.getRange("G12:G17").values = confirmatoryV7 ? [
  ["La v7 final no supera la puerta conjunta: cumple cinco de seis criterios y falla exactitud de postura."],
  ["Recuperación, precisión, cobertura, vacíos falsos y contexto social cumplen sus umbrales prerregistrados."],
  ["La exactitud de postura fue 24/37 (64.9%). Once fuentes gold discusses fueron etiquetadas supports; es el error dominante."],
  ["El acuerdo humano fue alto: postura 89.2% (κ=0.742), cobertura 95.8% (κ=0.814) y contexto social 100%."],
  ["El resultado es defendible como limitación final: la política recupera evidencia pertinente, pero sobreafirma supports frente a discusses."],
  ["La regla de cierre impide otra iteración post hoc sobre esta evidencia; la tesis debe reportar la v7 como confirmación final fallida."],
] : [
  ["La selección de fuentes es fuerte: las 22 fuentes recuperadas y evaluables fueron relevantes (100%; IC95% 85.1%–100%)."],
  ["El cuello de botella es la recuperación: solo 11/20 publicaciones obtuvieron alguna fuente y 8/9 vacíos fueron falsos."],
  ["La postura es moderada: 14/22 coincidencias (63.6%); cinco supports fueron tratados como discusses y tres discusses como supports."],
  ["La cobertura suficiente alcanzó 7/19 casos con evidencia existente (36.8%); doce casos omitieron al menos una fuente importante."],
  ["El resultado respalda conservar el módulo, pero priorizar recall, contexto y calibración supports/discusses antes de presentarlo como verificación robusta."],
  ["La inferencia es limitada: piloto estratificado pequeño, sin casos de X y sin umbral de aprobación preregistrado."],
];
sheet.getRange("G12:K17").format.font = bodyFont;
sheet.getRange("G12:K17").format.wrapText = true;
sheet.getRange("G12:K17").format.rowHeight = 45;

sheet.getRange("A17:E17").merge();
sheet.getRange("A17").values = [[confirmatoryV7 ? "Criterios prerregistrados" : "Distribución final de cobertura"]];
sheet.getRange("A17:E17").format = sectionFormat;
if (confirmatoryV7) {
  const criteria = summary.registered_criteria;
  sheet.getRange("A18:E24").values = [
    ["Criterio", "Umbral", "Resultado", "Estado", "Base"],
    ["Contenido devuelto", "≥80%", criteria.retrieval_content_at_least_80_percent.observed, criteria.retrieval_content_at_least_80_percent.passed ? "Cumple" : "No cumple", "21/24"],
    ["Precisión de fuentes", "≥90%", criteria.source_precision_at_least_90_percent.observed, criteria.source_precision_at_least_90_percent.passed ? "Cumple" : "No cumple", "37/37"],
    ["Cobertura útil", "≥80%", criteria.useful_coverage_at_least_80_percent.observed, criteria.useful_coverage_at_least_80_percent.passed ? "Cumple" : "No cumple", "22/22"],
    ["Exactitud de postura", "≥75%", criteria.stance_accuracy_at_least_75_percent.observed, criteria.stance_accuracy_at_least_75_percent.passed ? "Cumple" : "No cumple", "24/37"],
    ["Vacíos falsos", "≤20%", criteria.false_empty_rate_at_most_20_percent.observed, criteria.false_empty_rate_at_most_20_percent.passed ? "Cumple" : "No cumple", "0/3"],
    ["Contexto social correcto", "≥80%", criteria.social_context_correct_at_least_80_percent.observed, criteria.social_context_correct_at_least_80_percent.passed ? "Cumple" : "No cumple", "6/6"],
  ];
  sheet.getRange("A18:E18").format = headerFormat;
  sheet.getRange("A19:E24").format.font = bodyFont;
  sheet.getRange("C19:C24").format.numberFormat = "0.0%";
} else {
  sheet.getRange("A18:B22").values = [
  ["Estado", "Casos"],
  ["sufficient", summary.coverage_final.status_counts.sufficient ?? 0],
  ["partial", summary.coverage_final.status_counts.partial ?? 0],
  ["none", summary.coverage_final.status_counts.none ?? 0],
  ["no_evidence_found", summary.coverage_final.status_counts.no_evidence_found ?? 0],
  ];
  sheet.getRange("A18:B18").format = headerFormat;
  sheet.getRange("A19:B22").format.font = bodyFont;
}

const sourceSheet = addDataSheet(
  workbook, "Fuentes", sourceValues,
  [17, 14, 42, 22, 42, 38, 16, 19, 16, 19, 16, 16, 16, 18, 18, 50],
  [2, 4, 5, 15],
);
const coverageSheet = addDataSheet(
  workbook, "Cobertura", coverageValues,
  confirmatoryV7
    ? [15, 12, 44, 62, 22, 38, 17, 22, 22, 20, 18, 42, 20, 18, 52]
    : [15, 44, 22, 38, 17, 22, 22, 20, 18, 42, 18, 52],
  confirmatoryV7 ? [2, 3, 5, 11, 14] : [1, 3, 9, 11],
);
const auditSheet = addDataSheet(
  workbook, "Adjudicación", auditRaw,
  [16, 18, 15, 31, 31, 31, 70],
  [3, 4, 5, 6],
);

const method = workbook.worksheets.add("Método");
method.showGridLines = false;
method.getRange("A2:F2").merge();
method.getRange("A2").values = [["Método, definiciones y límites"]];
method.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
const methodRows = confirmatoryV7 ? [
  ["Elemento", "Definición"],
  ["Etapa", "Resultados finales de la evaluación confirmatoria v7. Se aplicaron cuatro decisiones de postura y una de cobertura mediante adjudicación ciega."],
  ["Muestra", "24 publicaciones inéditas congeladas: 18 web y 6 de X; 37 relaciones afirmación–fuente."],
  ["Precisión de fuentes", "Proporción de fuentes evaluables cuya postura final no fue unrelated."],
  ["Exactitud de postura", "Coincidencia entre evidence-policy-2026-10-27-v6 y la postura humana final."],
  ["Cobertura útil", "Casos sufficient o partial entre aquellos donde la revisión humana estableció que existía evidencia."],
  ["Vacío falso", "El sistema devolvió cero fuentes y la revisión humana estableció que existía evidencia, con final_coverage=none."],
  ["Contexto social", "Atribución correcta del autor y distinción entre el post analizado y el contenido citado, respondido o republicado."],
  ["Acuerdo", "Las métricas de acuerdo se calculan antes de adjudicar; las métricas del sistema usan consenso exacto más adjudicación."],
  ["Umbrales", "Seis criterios fijados antes de retrieval, anotación y adjudicación. Todos debían cumplirse simultáneamente."],
  ["Decisión", "La v7 cumple cinco criterios y falla exactitud de postura; por tanto, overall_passed=false."],
  ["Regla de cierre", "No se abre otra iteración post hoc con la misma evidencia. El resultado se reporta como limitación final de la tesis."],
] : [
  ["Elemento", "Definición"],
  ["Etapa", "Resultados finales. Las filas con acuerdo exacto conservan el consenso; los 4 desacuerdos de fuentes y 10 de cobertura usan decisión adjudicada y justificada."],
  ["Unidad de fuentes", "22 pares afirmación–fuente recuperados por el sistema en 11 de las 20 publicaciones."],
  ["Precisión de fuentes", "Proporción de fuentes evaluables cuya postura final no fue unrelated."],
  ["Exactitud de postura", "Coincidencia entre la etiqueta del sistema y la postura humana final."],
  ["Macro-F1 observado", "Media del F1 en las clases con soporte final; aquí solo supports y discusses."],
  ["Cobertura útil", "Casos sufficient o partial entre aquellos donde la revisión humana estableció que existía evidencia."],
  ["Cobertura suficiente", "Casos sufficient entre aquellos donde existía evidencia."],
  ["Vacío falso", "El sistema devolvió cero fuentes, pero la revisión independiente encontró evidencia relevante (final_coverage=none)."],
  ["Acuerdo", "Las métricas de acuerdo se calculan antes de adjudicar; no deben reinterpretarse como desempeño final del sistema."],
  ["Muestra", "20 publicaciones seleccionadas mediante muestreo estratificado del snapshot congelado. No estima prevalencia natural del feed."],
  ["X/social", "La instantánea no contenía publicaciones de X; el manejo de hilos, respuestas y quotes sigue requiriendo una prueba dedicada."],
  ["Umbral", "No se preregistró un criterio de aprobación. Los resultados sirven como diagnóstico del prototipo, no como certificación."],
];
const methodLastRow = 3 + methodRows.length;
method.getRange(`A4:B${methodLastRow}`).values = methodRows;
method.getRange("A4:B4").format = headerFormat;
method.getRange(`A5:B${methodLastRow}`).format.font = bodyFont;
method.getRange(`A5:B${methodLastRow}`).format.verticalAlignment = "top";
method.getRange(`B5:B${methodLastRow}`).format.wrapText = true;
method.getRange("A:A").format.columnWidth = 28;
method.getRange("B:B").format.columnWidth = 98;
method.getRange(`A5:B${methodLastRow}`).format.rowHeight = 42;

sheet.tabColor = "#243B53";
sourceSheet.tabColor = "#5B7C99";
coverageSheet.tabColor = "#5B7C99";
auditSheet.tabColor = "#A67C00";
method.tabColor = "#A8B5C2";
workbook.recalculate();

const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

await fs.mkdir(previewDir, { recursive: true });
const previews = [
  ["Resumen", confirmatoryV7 ? "A1:K24" : "A1:K23", "resumen.png"],
  ["Fuentes", `A1:P${sourceValues.length}`, "fuentes.png"],
  ["Cobertura", `A1:${confirmatoryV7 ? "O" : "L"}${coverageValues.length}`, "cobertura.png"],
  ["Adjudicación", `A1:G${auditRaw.length}`, "adjudicacion.png"],
  ["Método", `A1:B${methodLastRow}`, "metodo.png"],
];
for (const [sheetName, range, fileName] of previews) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(`${outputPath}.inspect.ndjson`, errorCheck.ndjson, "utf8");
console.log(JSON.stringify({ outputPath, previewDir, errorCheck: errorCheck.ndjson }, null, 2));
