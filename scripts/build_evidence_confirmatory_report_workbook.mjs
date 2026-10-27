import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) throw new Error(`Missing ${name}`);
  return process.argv[index + 1];
}

const preparationPath = option("--preparation-report");
const evaluationPath = option("--evaluation-report");
const errorsPath = option("--errors");
const predictionsPath = option("--predictions");
const goldPath = option("--gold");
const outputPath = option("--output");
const previewDir = option("--preview-dir");

const preparation = JSON.parse(await fs.readFile(preparationPath, "utf8"));
const evaluation = JSON.parse(await fs.readFile(evaluationPath, "utf8"));
const errorsCsv = (await fs.readFile(errorsPath, "utf8")).replace(/^\uFEFF/, "");
const predictionsCsv = (await fs.readFile(predictionsPath, "utf8")).replace(/^\uFEFF/, "");
const goldCsv = (await fs.readFile(goldPath, "utf8")).replace(/^\uFEFF/, "");

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Resumen");

async function appendCsvSheet(csvText, name) {
  const sourceBook = await Workbook.fromCSV(csvText, { sheetName: name });
  const source = sourceBook.worksheets.getItem(name).getUsedRange(true);
  const sheet = workbook.worksheets.add(name);
  sheet.getRangeByIndexes(0, 0, source.rowCount, source.columnCount).copyFrom(source, "values");
  return sheet;
}

const errors = await appendCsvSheet(errorsCsv, "Errores");
const predictions = await appendCsvSheet(predictionsCsv, "Predicciones");
const gold = await appendCsvSheet(goldCsv, "Gold");
const method = workbook.worksheets.add("Metodo");

const font = "Arial";
const navy = "#243F57";
const paleBlue = "#EAF0F6";
const paleGreen = "#E2F0D9";
const paleOrange = "#FCE4D6";
const paleRed = "#F4CCCC";
const bootstrap = evaluation.grouped_bootstrap;
const report = evaluation.classification_report;

summary.showGridLines = false;
summary.getRange("A2:J2").merge();
summary.getRange("A2").values = [["Evaluación confirmatoria de la política de evidencia v3"]];
summary.getRange("A2:J2").format = { font: { name: font, size: 16, bold: true, color: "#1F2937" }, rowHeight: 30 };
summary.getRange("A4:B4").values = [["Métrica", "Resultado"]];
summary.getRange("A5:B14").values = [
  ["Pares evaluados", evaluation.sample_size],
  ["Grupos de fuentes", preparation.groups],
  ["Exactitud", evaluation.accuracy],
  ["IC 95% de exactitud", `${(bootstrap.accuracy_95_percentile_interval.low * 100).toFixed(1)}%–${(bootstrap.accuracy_95_percentile_interval.high * 100).toFixed(1)}%`],
  ["Macro-F1 de cuatro clases", evaluation.macro_f1_four_class],
  ["IC 95% de macro-F1", `${(bootstrap.macro_f1_four_class_95_percentile_interval.low * 100).toFixed(1)}%–${(bootstrap.macro_f1_four_class_95_percentile_interval.high * 100).toFixed(1)}%`],
  ["Errores", evaluation.error_count],
  ["Acuerdo humano previo", preparation.human_agreement_before_adjudication.observed],
  ["Kappa humano previo", preparation.human_agreement_before_adjudication.cohen_kappa],
  ["Solapamiento con desarrollo", preparation.exact_overlap_with_evidence_development + preparation.claim_overlap_with_evidence_development],
];
summary.getRange("D4:H4").values = [["Clase", "Precision", "Recall", "F1", "Soporte"]];
summary.getRange("D5:H8").values = ["supports", "refutes", "discusses", "unrelated"].map((label) => [
  label,
  report[label].precision,
  report[label].recall,
  report[label]["f1-score"],
  report[label].support,
]);
summary.getRange("D10:H10").values = [["Gold \\ Modelo", ...evaluation.confusion_matrix_label_order]];
summary.getRange("D11:H14").values = evaluation.confusion_matrix_label_order.map((label, index) => [label, ...evaluation.confusion_matrix[index]]);
summary.getRange("A16:J16").merge();
summary.getRange("A16").values = [["Conclusión y alcance"]];
summary.getRange("A17:J20").merge();
summary.getRange("A17").values = [["La política v3 obtuvo 96.25% de exactitud y macro-F1 de 96.20% en un gold externo congelado, con cuatro clases y cero solapamiento con el desarrollo. Es evidencia confirmatoria del razonamiento por pares. No mide búsqueda web, prevalencia natural ni una puerta de aprobación prerregistrada. La política debe permanecer congelada; el siguiente ensayo debe evaluar recuperación y clasificación de extremo a extremo."]];

for (const range of ["A4:B4", "D4:H4", "D10:H10", "A16:J16"]) {
  summary.getRange(range).format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center" };
}
summary.getRange("A5:A14").format.fill = paleBlue;
summary.getRange("D5:D8").format.fill = paleBlue;
summary.getRange("D11:D14").format.fill = paleBlue;
summary.getRange("B7:B7").format.fill = paleGreen;
summary.getRange("B9:B9").format.fill = paleGreen;
summary.getRange("A17:J20").format = { fill: paleOrange, font: { name: font, size: 10, color: "#1F2937" }, wrapText: true, verticalAlignment: "top" };
summary.getRange("A4:J20").format.font = { name: font, size: 10, color: "#1F2937" };
summary.getRange("B7:B7").format.numberFormat = "0.00%";
summary.getRange("B9:B9").format.numberFormat = "0.00%";
summary.getRange("B12:B13").format.numberFormat = "0.0%";
summary.getRange("E5:G8").format.numberFormat = "0.0%";
summary.getRange("A:A").format.columnWidth = 34;
summary.getRange("B:B").format.columnWidth = 24;
summary.getRange("C:C").format.columnWidth = 4;
summary.getRange("D:D").format.columnWidth = 20;
summary.getRange("E:H").format.columnWidth = 14;
summary.getRange("I:J").format.columnWidth = 12;
summary.getRange("A4:J20").format.verticalAlignment = "top";

function styleDataSheet(sheet, widths, wrappedColumns = []) {
  const used = sheet.getUsedRange(true);
  const rows = used.rowCount;
  const cols = used.columnCount;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(1);
  sheet.getRangeByIndexes(0, 0, rows, cols).format.font = { name: font, size: 10, color: "#1F2937" };
  sheet.getRangeByIndexes(0, 0, 1, cols).format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, rowHeight: 34 };
  sheet.getRangeByIndexes(1, 0, Math.max(1, rows - 1), cols).format.verticalAlignment = "top";
  for (let i = 0; i < widths.length; i += 1) sheet.getRangeByIndexes(0, i, rows, 1).format.columnWidth = widths[i];
  for (const column of wrappedColumns) sheet.getRange(`${column}2:${column}${rows}`).format.wrapText = true;
  return { rows, cols };
}

const errorDims = styleDataSheet(errors, [20, 48, 18, 42, 62, 18, 20, 68], ["B", "D", "E", "H"]);
errors.getRange(`F2:H${errorDims.rows}`).format.fill = paleRed;
styleDataSheet(predictions, [20, 18, 20, 66, 24, 30, 68], ["D"]);
styleDataSheet(gold, [20, 24, 48, 18, 42, 66, 42, 18, 18, 28, 52], ["C", "E", "F", "K"]);

method.showGridLines = false;
method.getRange("A2:B2").merge();
method.getRange("A2").values = [["Método y límites"]];
method.getRange("A2:B2").format = { font: { name: font, size: 15, bold: true, color: "#1F2937" }, rowHeight: 28 };
method.getRange("A4:B4").values = [["Elemento", "Definición"]];
method.getRange("A5:B14").values = [
  ["Gold", `Challenge 05; estado ${preparation.source_status}; SHA-256 ${preparation.source_gold_sha256}.`],
  ["Independencia", "El gold fue congelado antes de la política v3 y no presenta solapamiento exacto ni por afirmación con las muestras de desarrollo de evidencia."],
  ["Anotación humana", `Doble anotación independiente: acuerdo ${(preparation.human_agreement_before_adjudication.observed * 100).toFixed(1)}%, κ=${preparation.human_agreement_before_adjudication.cohen_kappa.toFixed(3)}; dos casos adjudicados.`],
  ["Diseño", "80 pares agrupados en 20 fuentes, con distribución controlada cercana al balance entre las cuatro clases."],
  ["Prueba", "Clasificación de pares fijos con gemini-3.5-flash-lite y evidence-policy-2026-10-22-v3. No se realizó una nueva búsqueda web."],
  ["Incertidumbre", `Bootstrap percentil de ${bootstrap.repetitions} repeticiones, remuestreando group_id para conservar la dependencia entre pares de una misma fuente.`],
  ["Prevalencia", "La muestra controlada no representa la frecuencia natural de supports, refutes, discusses y unrelated en producción."],
  ["Umbral", "No se prerregistró un umbral de aprobación específico para esta política. Las métricas se reportan descriptivamente."],
  ["Congelamiento", "No se ajustará el prompt, las reglas ni los umbrales a partir de los tres errores de esta prueba confirmatoria."],
  ["Siguiente paso", "Evaluar de extremo a extremo la búsqueda, selección y clasificación de fuentes sobre publicaciones nuevas."],
];
method.getRange("A4:B4").format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
method.getRange("A5:A14").format.fill = paleBlue;
method.getRange("B11:B14").format.fill = paleOrange;
method.getRange("A5:B14").format = { font: { name: font, size: 10, color: "#1F2937" }, verticalAlignment: "top" };
method.getRange("B5:B14").format.wrapText = true;
method.getRange("A:A").format.columnWidth = 28;
method.getRange("B:B").format.columnWidth = 108;

workbook.recalculate();
const summaryCheck = await workbook.inspect({ kind: "table", range: "Resumen!A2:J20", include: "values,formulas", tableMaxRows: 22, tableMaxCols: 10 });
const errorsCheck = await workbook.inspect({ kind: "table", range: `Errores!A1:H${errorDims.rows}`, include: "values,formulas", tableMaxRows: 8, tableMaxCols: 8 });
const formulaErrors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });

await fs.mkdir(previewDir, { recursive: true });
for (const name of ["Resumen", "Errores", "Metodo"]) {
  const preview = await workbook.render({ sheetName: name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${name.toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, summaryCheck: summaryCheck.ndjson, errorsCheck: errorsCheck.ndjson, formulaErrors: formulaErrors.ndjson }));
