import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const args = process.argv.slice(2);
const valueAfter = (flag, fallback) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : fallback;
};

const inputDir = valueAfter("--input-dir", "output/evidence_end_to_end_v4_blind_final_2026_10_25");
const outputPath = valueAfter("--output", "outputs/evidence-end-to-end-v4-blind-2026-10-25/evaluacion_v4_final.xlsx");
const previewDir = valueAfter("--preview-dir", "output/evidence_end_to_end_v4_blind_final_preview");
const reportMode = valueAfter("--report-mode", "v4-confirmatory");
const isV5Development = reportMode === "v5-development";

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

function percentText(value) {
  return `${(100 * value).toFixed(1)}%`;
}

function intervalText(interval) {
  return `${percentText(interval[0])}–${percentText(interval[1])}`;
}

const summary = JSON.parse(await fs.readFile(path.join(inputDir, "final_summary.json"), "utf8"));
const sourceRaw = await csvValues("final_source_results.csv");
const coverageRaw = await csvValues("final_coverage_results.csv");
const auditRaw = await csvValues(isV5Development ? "provenance_audit.csv" : "adjudication_audit.csv");

const sourceValues = selectColumns(sourceRaw, isV5Development ? [
  "evidence_id", "case_id", "claim", "source_name", "source_title", "source_url",
  "source_role", "model_stance", "final_stance", "model_matches_final",
  "review_provenance", "human_decision_source", "adjudication_rationale",
] : [
  "evidence_id", "case_id", "claim", "source_name", "source_title", "source_url",
  "model_stance", "annotator_a_status", "annotator_a_stance", "annotator_b_status",
  "final_stance", "model_matches_final", "decision_source", "adjudication_rationale",
]);
const coverageValues = selectColumns(coverageRaw, isV5Development ? [
  "case_id", "claim", "original_source", "original_url", "returned_source_count",
  "independent_source_count", "primary_context_count", "final_coverage", "final_missing",
  "final_missing_url", "review_provenance", "human_decision_source", "adjudication_rationale",
] : [
  "case_id", "claim", "original_source", "original_url", "returned_source_count",
  "annotator_a_coverage", "annotator_b_coverage", "final_coverage", "final_missing",
  "final_missing_url", "decision_source", "adjudication_rationale",
]);
const sourceLastRow = sourceValues.length;
const coverageLastRow = coverageValues.length;
const finalStanceColumn = isV5Development ? "I" : "K";
const modelStanceColumn = isV5Development ? "H" : "G";
const modelMatchColumn = isV5Development ? "J" : "L";

const workbook = Workbook.create();
const summarySheet = workbook.worksheets.add("Resumen");
const sourceSheet = addDataSheet(workbook, "Fuentes", sourceValues,
  isV5Development
    ? [17, 14, 42, 22, 42, 38, 20, 16, 16, 18, 22, 22, 54]
    : [17, 14, 42, 22, 42, 38, 16, 19, 18, 19, 16, 18, 18, 54],
  isV5Development ? [2, 4, 5, 12] : [2, 4, 5, 13]);
const coverageSheet = addDataSheet(workbook, "Cobertura", coverageValues,
  isV5Development
    ? [15, 44, 22, 38, 17, 18, 18, 20, 18, 42, 22, 22, 54]
    : [15, 44, 22, 38, 17, 22, 22, 20, 18, 42, 18, 54],
  isV5Development ? [1, 3, 9, 12] : [1, 3, 9, 11]);
const auditSheet = addDataSheet(workbook, isV5Development ? "Trazabilidad" : "Adjudicación", auditRaw,
  isV5Development ? [16, 20, 15, 24, 22, 48] : [16, 18, 15, 31, 31, 31, 72],
  isV5Development ? [4, 5] : [3, 4, 5, 6]);
const method = workbook.worksheets.add("Método");

summarySheet.showGridLines = false;
summarySheet.getRange("A2:F2").merge();
summarySheet.getRange("A2").values = [[isV5Development
  ? "Regresión de desarrollo v5 — resultados humanos finales"
  : "Evaluación ciega integral de evidencia v4 — resultados finales"]];
summarySheet.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
summarySheet.getRange("A4:F4").values = [[isV5Development ? "Criterio de referencia" : "Criterio prerregistrado", "Umbral", "Resultado final", "Base", "Estado", "Interpretación"]];
summarySheet.getRange("A4:F4").format = headerFormat;
summarySheet.getRange("A5:F9").values = [
  ["Publicaciones con fuentes", 0.80, null, isV5Development ? `${summary.system_run.retrieval_success_n}/20` : "14/20", null, isV5Development ? "Todas las publicaciones devolvieron al menos contexto utilizable." : "La recuperación quedó por debajo del mínimo de 16 publicaciones."],
  ["Precisión de fuentes evaluables", 0.90, null, `${summary.retrieval_source_quality_final.relevant_n}/${summary.retrieval_source_quality_final.evaluable_n}`, null, `Fuentes independientes relevantes. IC95% Wilson: ${intervalText(summary.retrieval_source_quality_final.precision_wilson_95)}.`],
  ["Cobertura útil", 0.80, null, `${summary.coverage_final.useful_coverage_n}/${summary.coverage_final.evidence_exists_n}`, null, isV5Development ? "Los veinte casos fueron adjudicados como suficientes; tres usan solo contexto primario." : "Incluye sufficient y partial entre casos donde la revisión determinó que existía evidencia."],
  ["Exactitud de postura", 0.75, null, `${summary.system_stance_final.accuracy_count}/${summary.system_stance_final.n}`, null, `La incertidumbre sigue siendo amplia. IC95% Wilson: ${intervalText(summary.system_stance_final.accuracy_wilson_95)}.`],
  ["Tasa de vacíos falsos", 0.20, null, isV5Development ? "0 casos vacíos" : "6/6", null, isV5Development ? "No hubo conjuntos vacíos; se observaron cero vacíos falsos y la tasa tiene denominador cero." : "Los seis resultados sin fuentes omitieron evidencia que la revisión humana consideró pertinente."],
];
summarySheet.getRange("C5").formulas = [[`=COUNTIFS(Cobertura!$E$2:$E$${coverageLastRow},">0")/${coverageLastRow - 1}`]];
summarySheet.getRange("C6").formulas = [[`=COUNTIFS(Fuentes!$${finalStanceColumn}$2:$${finalStanceColumn}$${sourceLastRow},"<>unrelated")/COUNTA(Fuentes!$${finalStanceColumn}$2:$${finalStanceColumn}$${sourceLastRow})`]];
summarySheet.getRange("C7").formulas = [[`=(COUNTIFS(Cobertura!$H$2:$H$${coverageLastRow},"sufficient")+COUNTIFS(Cobertura!$H$2:$H$${coverageLastRow},"partial"))/COUNTA(Cobertura!$H$2:$H$${coverageLastRow})`]];
summarySheet.getRange("C8").formulas = [[`=COUNTIFS(Fuentes!$${modelMatchColumn}$2:$${modelMatchColumn}$${sourceLastRow},"True")/COUNTA(Fuentes!$${modelMatchColumn}$2:$${modelMatchColumn}$${sourceLastRow})`]];
summarySheet.getRange("C9").formulas = [[`=IF(COUNTIFS(Cobertura!$E$2:$E$${coverageLastRow},0)=0,0,COUNTIFS(Cobertura!$E$2:$E$${coverageLastRow},0,Cobertura!$H$2:$H$${coverageLastRow},"none")/COUNTIFS(Cobertura!$E$2:$E$${coverageLastRow},0))`]];
summarySheet.getRange("E5").formulas = [["=IF(C5>=B5,\"Cumple\",\"No cumple\")"]];
summarySheet.getRange("E5:E8").fillDown();
summarySheet.getRange("E9").formulas = [["=IF(C9<=B9,\"Cumple\",\"No cumple\")"]];
summarySheet.getRange("A5:F9").format.font = bodyFont;
summarySheet.getRange("A5:F9").format.verticalAlignment = "top";
summarySheet.getRange("A5:A9").format.fill = "#EEF3F7";
summarySheet.getRange("B5:C9").format.numberFormat = "0.0%";
summarySheet.getRange("F5:F9").format.wrapText = true;
summarySheet.getRange("A5:F9").format.rowHeight = 45;
summarySheet.getRange("E5:E9").conditionalFormats.add("containsText", { text: "No cumple", format: { fill: "#FDECEC", font: { bold: true, color: "#A61B1B" } } });
summarySheet.getRange("A:A").format.columnWidth = 34;
summarySheet.getRange("B:B").format.columnWidth = 14;
summarySheet.getRange("C:C").format.columnWidth = 18;
summarySheet.getRange("D:D").format.columnWidth = 14;
summarySheet.getRange("E:E").format.columnWidth = 16;
summarySheet.getRange("F:F").format.columnWidth = 66;

summarySheet.getRange("A12:F12").merge();
summarySheet.getRange("A12").values = [["Conclusión"]];
summarySheet.getRange("A12:F12").format = sectionFormat;
summarySheet.getRange("A13:B17").values = [
  ["Decisión global", null],
  ["Criterios cumplidos", isV5Development ? `${summary.reference_criteria_passed_n} de 5` : "2 de 5"],
  ["Fortalezas", isV5Development ? "Recuperación completa, precisión de fuentes y cobertura útil." : "Precisión de fuentes y clasificación de postura."],
  ["Límite principal", isV5Development ? "Es una regresión de desarrollo sobre la misma muestra, no una confirmación independiente." : "Recuperación insuficiente, cobertura útil baja y vacíos falsos."],
  ["Siguiente prioridad", isV5Development ? "Ejecutar una muestra confirmatoria fresca e incluir casos de X con quotes, respuestas e hilos." : "Mejorar la recuperación y el tratamiento de publicaciones originales o de opinión antes de repetir una prueba ciega."],
];
for (let row = 13; row <= 17; row += 1) summarySheet.getRange(`B${row}:F${row}`).merge();
summarySheet.getRange("B13").formulas = [[isV5Development
  ? '=IF(COUNTIFS(E5:E9,"Cumple")=5,"CUMPLE UMBRALES DE REFERENCIA","NO CUMPLE UMBRALES DE REFERENCIA")'
  : '=IF(COUNTIFS(E5:E9,"Cumple")=5,"APROBADA","NO APROBADA")']];
summarySheet.getRange("A13:F17").format.font = bodyFont;
summarySheet.getRange("A13:A17").format.fill = "#EEF3F7";
summarySheet.getRange("B13:F17").format.wrapText = true;
summarySheet.getRange("A13:F17").format.rowHeight = 38;
summarySheet.getRange("B13").format.font = { name: fontFamily, size: 10, bold: true, color: isV5Development ? "#176B3A" : "#A61B1B" };

summarySheet.getRange("H4:M4").merge();
summarySheet.getRange("H4").values = [["Matriz de confusión: postura humana final × modelo"]];
summarySheet.getRange("H4:M4").format = sectionFormat;
summarySheet.getRange("H5:M10").values = [
  ["Humano / modelo", "supports", "refutes", "discusses", "unrelated", "Total"],
  ["supports", null, null, null, null, null],
  ["refutes", null, null, null, null, null],
  ["discusses", null, null, null, null, null],
  ["unrelated", null, null, null, null, null],
  ["Total", null, null, null, null, null],
];
summarySheet.getRange("I6").formulas = [[`=COUNTIFS(Fuentes!$${finalStanceColumn}$2:$${finalStanceColumn}$${sourceLastRow},$H6,Fuentes!$${modelStanceColumn}$2:$${modelStanceColumn}$${sourceLastRow},I$5)`]];
summarySheet.getRange("I6:L9").fillDown();
summarySheet.getRange("I6:L9").fillRight();
for (let row = 6; row <= 9; row += 1) summarySheet.getRange(`M${row}`).formulas = [[`=SUM(I${row}:L${row})`]];
for (let col of ["I", "J", "K", "L"]) summarySheet.getRange(`${col}10`).formulas = [[`=SUM(${col}6:${col}9)`]];
summarySheet.getRange("M10").formulas = [["=SUM(M6:M9)"]];
summarySheet.getRange("H5:M5").format = headerFormat;
summarySheet.getRange("H6:M10").format.font = bodyFont;
summarySheet.getRange("H6:H10").format.fill = "#EEF3F7";
summarySheet.getRange("H:H").format.columnWidth = 24;
summarySheet.getRange("I:M").format.columnWidth = 14;

summarySheet.getRange("H12:M12").merge();
summarySheet.getRange("H12").values = [[isV5Development ? "Acuerdo en la revisión focalizada" : "Acuerdo antes de adjudicar"]];
summarySheet.getRange("H12:M12").format = sectionFormat;
summarySheet.getRange("H13:J17").values = [
  ["Medida", "Resultado", "Base"],
  ["Evaluabilidad de fuentes", (isV5Development ? summary.focused_interannotator_agreement_pre_adjudication : summary.interannotator_agreement_pre_adjudication).source_agreement.evaluability_exact, isV5Development ? "13 pares nuevos" : "24 pares"],
  ["Postura entre pares evaluables", (isV5Development ? summary.focused_interannotator_agreement_pre_adjudication : summary.interannotator_agreement_pre_adjudication).source_agreement.stance_exact_among_both_evaluable, isV5Development ? "13 pares nuevos" : "22 pares"],
  ["Cobertura por publicación", (isV5Development ? summary.focused_interannotator_agreement_pre_adjudication : summary.interannotator_agreement_pre_adjudication).coverage_agreement.coverage_exact, isV5Development ? "16 casos cambiados" : "20 casos"],
  ["Existencia de evidencia faltante", (isV5Development ? summary.focused_interannotator_agreement_pre_adjudication : summary.interannotator_agreement_pre_adjudication).coverage_agreement.missing_exact, isV5Development ? "16 casos cambiados" : "20 casos"],
];
summarySheet.getRange("H13:J13").format = headerFormat;
summarySheet.getRange("H14:J17").format.font = bodyFont;
summarySheet.getRange("I14:I17").format.numberFormat = "0.0%";
summarySheet.getRange("H14:H17").format.fill = "#EEF3F7";

method.showGridLines = false;
method.getRange("A2:F2").merge();
method.getRange("A2").values = [["Método, criterios y límites"]];
method.getRange("A2:F2").format = { font: { name: fontFamily, size: 15, bold: true, color: "#172033" } };
const methodRows = isV5Development ? [
  ["Elemento", "Definición"],
  ["Diseño", "Regresión de desarrollo sobre la misma muestra congelada de 20 publicaciones usada para diagnosticar v4. No es una evaluación confirmatoria fresca."],
  ["Unidad", `${summary.independent_source_pairs} pares afirmación–fuente independientes y ${summary.coverage_cases} publicaciones.`],
  ["Revisión humana", `${summary.review_provenance.v5_focused_source_n} fuentes nuevas y ${summary.review_provenance.v5_focused_coverage_n} conjuntos cambiados se revisaron de forma ciega. Los registros sin cambios reutilizan decisiones previas solo por coincidencia exacta de case_id y URL.`],
  ["Contexto primario", `${summary.primary_context_only_cases} casos contienen solo la publicación original. Sirve para interpretar citas u opiniones, pero no participa en precisión ni postura de fuentes independientes.`],
  ["Precisión de fuentes", "Proporción de fuentes independientes evaluables cuya postura humana final no fue unrelated."],
  ["Exactitud de postura", "Coincidencia entre evidence-policy v5 y la postura humana final en fuentes independientes."],
  ["Cobertura útil", "Casos sufficient o partial entre aquellos donde la revisión humana estableció que existía evidencia."],
  ["Vacío falso", "El sistema devolvió cero fuentes, pero la revisión humana estableció que sí existía evidencia pertinente. En v5 no hubo conjuntos vacíos."],
  ["Umbrales", "Se usan como referencia los umbrales fijados para v4: recuperación ≥16/20; precisión ≥90%; cobertura útil ≥80%; postura ≥75%; vacíos falsos ≤20%."],
  ["Interpretación", "Cumplir estos umbrales muestra corrección en desarrollo, pero no constituye confirmación independiente porque la misma muestra guio los cambios."],
  ["Acuerdo", "El acuerdo mostrado corresponde solo a la revisión focalizada antes de adjudicar. No debe combinarse directamente con el acuerdo de la ronda v4."],
  ["Clases", "No hubo ejemplos humanos finales refutes ni unrelated; el macro-F1 fijo de cuatro clases no es la métrica central."],
  ["X/social", "La muestra no contiene publicaciones de X. Quotes, respuestas e hilos requieren una evaluación social independiente."],
  ["Siguiente prueba", "Congelar una muestra nueva, incluir casos sociales y repetir doble anotación sin reutilizar estas decisiones."],
] : [
  ["Elemento", "Definición"],
  ["Diseño", "Muestra fresca, congelada y ciega de 20 publicaciones web estratificadas. Los casos no se usaron para desarrollar las reglas v4."],
  ["Unidad", `${summary.source_pairs} pares afirmación–fuente y ${summary.coverage_cases} publicaciones.`],
  ["Adjudicación", `${summary.adjudicated_source_n} desacuerdos de fuente y ${summary.adjudicated_coverage_n} desacuerdos de cobertura se resolvieron sin usar la etiqueta del sistema como criterio.`],
  ["Precisión de fuentes", "Proporción de fuentes evaluables cuya postura final no fue unrelated."],
  ["Exactitud de postura", "Coincidencia entre la etiqueta del sistema y la postura humana final."],
  ["Cobertura útil", "Casos sufficient o partial entre aquellos donde la revisión humana estableció que existía evidencia."],
  ["Vacío falso", "El sistema devolvió cero fuentes, pero la revisión humana estableció que sí existía evidencia pertinente."],
  ["Criterios", "Recuperación ≥16/20; precisión de fuentes ≥90%; cobertura útil ≥80%; exactitud de postura ≥75%; vacíos falsos ≤20%."],
  ["Registro temporal", "Los cinco umbrales se fijaron antes de ejecutar y anotar la muestra v4."],
  ["Acuerdo", "Las métricas de acuerdo se calcularon antes de adjudicar. Describen consistencia entre anotadores, no desempeño del sistema."],
  ["Población", "La muestra estratificada no estima la prevalencia natural del feed."],
  ["Incertidumbre", "Los denominadores son pequeños. Los intervalos de Wilson muestran que las estimaciones todavía tienen incertidumbre amplia."],
  ["Clases", "No hubo casos humanos finales refutes ni unrelated; por eso el macro-F1 fijo de cuatro clases no es una medida central en esta ronda."],
  ["X/social", "La instantánea no contiene publicaciones de X. Hilos, respuestas y quotes requieren una prueba social independiente."],
];
const methodLastRow = 3 + methodRows.length;
method.getRange(`A4:B${methodLastRow}`).values = methodRows;
method.getRange("A4:B4").format = headerFormat;
method.getRange(`A5:B${methodLastRow}`).format.font = bodyFont;
method.getRange(`A5:B${methodLastRow}`).format.verticalAlignment = "top";
method.getRange(`B5:B${methodLastRow}`).format.wrapText = true;
method.getRange("A:A").format.columnWidth = 29;
method.getRange("B:B").format.columnWidth = 104;
method.getRange(`A5:B${methodLastRow}`).format.rowHeight = 44;

summarySheet.tabColor = "#243B53";
sourceSheet.tabColor = "#5B7C99";
coverageSheet.tabColor = "#5B7C99";
auditSheet.tabColor = "#A67C00";
method.tabColor = "#A8B5C2";
workbook.recalculate();

const summaryCheck = await workbook.inspect({ kind: "table", range: "Resumen!A4:M17", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 13, maxChars: 14000 });
const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

await fs.mkdir(previewDir, { recursive: true });
const previews = [
  ["Resumen", "A1:M17", "resumen.png"],
  ["Fuentes", isV5Development ? "A1:M9" : "A1:N9", "fuentes.png"],
  ["Cobertura", isV5Development ? "A1:M9" : "A1:L9", "cobertura.png"],
  [isV5Development ? "Trazabilidad" : "Adjudicación", `A1:${isV5Development ? "F" : "G"}${auditRaw.length}`, isV5Development ? "trazabilidad.png" : "adjudicacion.png"],
  ["Método", `A1:F${methodLastRow}`, "metodo.png"],
];
for (const [sheetName, range, fileName] of previews) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(`${outputPath}.inspect.ndjson`, `${summaryCheck.ndjson}\n${errorCheck.ndjson}`, "utf8");
console.log(JSON.stringify({ outputPath, previewDir, summaryCheck: summaryCheck.ndjson, errorCheck: errorCheck.ndjson }, null, 2));
