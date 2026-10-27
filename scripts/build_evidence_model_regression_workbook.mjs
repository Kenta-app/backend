import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) throw new Error(`Missing ${name}`);
  return process.argv[index + 1];
}

const beforePath = option("--before-report");
const afterPath = option("--after-report");
const predictionsPath = option("--predictions");
const errorsPath = option("--errors");
const outputPath = option("--output");
const previewDir = option("--preview-dir");

const before = JSON.parse(await fs.readFile(beforePath, "utf8"));
const after = JSON.parse(await fs.readFile(afterPath, "utf8"));
const predictionsCsv = (await fs.readFile(predictionsPath, "utf8")).replace(/^\uFEFF/, "");
const errorsCsv = (await fs.readFile(errorsPath, "utf8")).replace(/^\uFEFF/, "");

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Resumen");
const predictionBook = await Workbook.fromCSV(predictionsCsv, { sheetName: "Predicciones" });
const predictionSource = predictionBook.worksheets.getItem("Predicciones").getUsedRange(true);
const predictions = workbook.worksheets.add("Predicciones");
predictions.getRangeByIndexes(0, 0, predictionSource.rowCount, predictionSource.columnCount).copyFrom(predictionSource, "values");
const errorBook = await Workbook.fromCSV(errorsCsv, { sheetName: "Errores" });
const errorSource = errorBook.worksheets.getItem("Errores").getUsedRange(true);
const errors = workbook.worksheets.add("Errores");
errors.getRangeByIndexes(0, 0, errorSource.rowCount, errorSource.columnCount).copyFrom(errorSource, "values");
const method = workbook.worksheets.add("Metodo");

const font = "Arial";
const navy = "#243F57";
const paleBlue = "#EAF0F6";
const paleGreen = "#E2F0D9";
const paleOrange = "#FCE4D6";
const paleRed = "#F4CCCC";
const pct = (value) => Number(value);

summary.showGridLines = false;
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [["Regresión del modelo sobre el desafío dirigido"]];
summary.getRange("A2:H2").format = { font: { name: font, size: 16, bold: true, color: "#1F2937" }, rowHeight: 30 };
summary.getRange("A4:D4").values = [["Métrica", "v2", "v3", "Cambio"]];
summary.getRange("A5:D9").values = [
  ["Exactitud", pct(before.accuracy), pct(after.accuracy), pct(after.accuracy - before.accuracy)],
  ["Macro-F1 de clases observadas", pct(before.macro_f1_observed_classes), pct(after.macro_f1_observed_classes), pct(after.macro_f1_observed_classes - before.macro_f1_observed_classes)],
  ["F1 refutes", pct(before.classification_report.refutes["f1-score"]), pct(after.classification_report.refutes["f1-score"]), pct(after.classification_report.refutes["f1-score"] - before.classification_report.refutes["f1-score"])],
  ["F1 discusses", pct(before.classification_report.discusses["f1-score"]), pct(after.classification_report.discusses["f1-score"]), pct(after.classification_report.discusses["f1-score"] - before.classification_report.discusses["f1-score"])],
  ["F1 unrelated", pct(before.classification_report.unrelated["f1-score"]), pct(after.classification_report.unrelated["f1-score"]), pct(after.classification_report.unrelated["f1-score"] - before.classification_report.unrelated["f1-score"])],
];
summary.getRange("A11:B11").values = [["Control", "Resultado"]];
summary.getRange("A12:B17").values = [
  ["Casos", after.sample_size],
  ["Errores v2", before.error_count],
  ["Errores v3", after.error_count],
  ["Versión evaluada", after.policy_version],
  ["Modelo", after.model],
  ["Decisión", "Congelar v3 y pasar a una muestra confirmatoria nueva; no ajustar los tres casos residuales con este mismo conjunto."],
];
summary.getRange("F4:J4").values = [["Gold \\ Modelo", ...after.confusion_matrix_label_order]];
summary.getRange("F5:J8").values = after.confusion_matrix_label_order.map((label, index) => [label, ...after.confusion_matrix[index]]);
summary.getRange("F10:J10").merge();
summary.getRange("F10").values = [["Interpretación"]];
summary.getRange("F11:J14").merge();
summary.getRange("F11").values = [["La v3 resolvió los errores repetidos de ausencia de pruebas y coincidencia superficial. Los tres errores restantes son casos de frontera. La muestra no contiene supports gold y fue utilizada durante el desarrollo, por lo que no es una validación confirmatoria independiente."]];

for (const range of ["A4:D4", "A11:B11", "F4:J4", "F10:J10"]) {
  summary.getRange(range).format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center" };
}
summary.getRange("A5:A9").format.fill = paleBlue;
summary.getRange("A12:A17").format.fill = paleBlue;
summary.getRange("F5:F8").format.fill = paleBlue;
summary.getRange("C5:C9").format.fill = paleGreen;
summary.getRange("D5:D9").format.fill = paleGreen;
summary.getRange("B17").format.fill = paleOrange;
summary.getRange("F11:J14").format = { fill: paleOrange, font: { name: font, size: 10, color: "#1F2937" }, wrapText: true, verticalAlignment: "top" };
summary.getRange("A4:J17").format.font = { name: font, size: 10, color: "#1F2937" };
summary.getRange("B5:D9").format.numberFormat = "0.0%";
summary.getRange("A:A").format.columnWidth = 34;
summary.getRange("B:B").format.columnWidth = 27;
summary.getRange("C:D").format.columnWidth = 17;
summary.getRange("E:E").format.columnWidth = 4;
summary.getRange("F:F").format.columnWidth = 20;
summary.getRange("G:J").format.columnWidth = 14;
summary.getRange("B17").format.wrapText = true;
summary.getRange("A4:J17").format.verticalAlignment = "top";

function styleDataSheet(sheet, rows, cols, widths, highlightRange = null) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(1);
  sheet.getRangeByIndexes(0, 0, rows, cols).format.font = { name: font, size: 10, color: "#1F2937" };
  sheet.getRangeByIndexes(0, 0, 1, cols).format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, rowHeight: 34 };
  sheet.getRangeByIndexes(1, 0, Math.max(1, rows - 1), cols).format.verticalAlignment = "top";
  for (let i = 0; i < widths.length; i += 1) sheet.getRangeByIndexes(0, i, rows, 1).format.columnWidth = widths[i];
  if (highlightRange) sheet.getRange(highlightRange).format.fill = paleRed;
}

const predictionRows = predictions.getUsedRange(true).rowCount;
const predictionCols = predictions.getUsedRange(true).columnCount;
styleDataSheet(predictions, predictionRows, predictionCols, [20, 18, 20, 66, 24, 30, 68]);
predictions.getRange(`D2:D${predictionRows}`).format.wrapText = true;

const errorRows = errors.getUsedRange(true).rowCount;
const errorCols = errors.getUsedRange(true).columnCount;
styleDataSheet(errors, errorRows, errorCols, [20, 48, 18, 42, 62, 18, 20, 68], `F2:H${errorRows}`);
errors.getRange(`B2:E${errorRows}`).format.wrapText = true;
errors.getRange(`H2:H${errorRows}`).format.wrapText = true;

method.showGridLines = false;
method.getRange("A2:B2").merge();
method.getRange("A2").values = [["Método y límites"]];
method.getRange("A2:B2").format = { font: { name: font, size: 15, bold: true, color: "#1F2937" }, rowHeight: 28 };
method.getRange("A4:B4").values = [["Elemento", "Definición"]];
method.getRange("A5:B12").values = [
  ["Prueba", "Regresión de pares fijos: cada afirmación se clasificó contra la evidencia adjudicada, sin realizar una nueva búsqueda web."],
  ["Modelo", after.model],
  ["v2", "Regla conservadora inicial. Obtuvo 85.0% de exactitud y seis errores."],
  ["v3", "Añade reglas generales para afirmaciones compuestas, refutación por ausencia de pruebas y coincidencias superficiales. Obtuvo 92.5% y tres errores."],
  ["Reproducibilidad", `Prompt v3 SHA-256: ${after.prompt_sha256}`],
  ["Cobertura", "Gold final: 12 refutes, 8 discusses, 20 unrelated y 0 supports."],
  ["Límite", "El conjunto fue usado para desarrollo. No permite estimar desempeño confirmatorio ni F1 de supports."],
  ["Siguiente paso", "Congelar v3 y diseñar una muestra nueva, ciega y con soporte de las cuatro clases. Evaluar recuperación de fuentes en una prueba integral separada."],
];
method.getRange("A4:B4").format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
method.getRange("A5:A12").format.fill = paleBlue;
method.getRange("B11:B12").format.fill = paleOrange;
method.getRange("A5:B12").format = { font: { name: font, size: 10, color: "#1F2937" }, verticalAlignment: "top" };
method.getRange("B5:B12").format.wrapText = true;
method.getRange("A:A").format.columnWidth = 28;
method.getRange("B:B").format.columnWidth = 105;

workbook.recalculate();
const summaryCheck = await workbook.inspect({ kind: "table", range: "Resumen!A2:J17", include: "values,formulas", tableMaxRows: 18, tableMaxCols: 10 });
const errorCheck = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });

await fs.mkdir(previewDir, { recursive: true });
for (const name of ["Resumen", "Errores", "Metodo"]) {
  const preview = await workbook.render({ sheetName: name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${name.toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, summaryCheck: summaryCheck.ndjson, errorCheck: errorCheck.ndjson }));
