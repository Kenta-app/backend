import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) throw new Error(`Missing ${name}`);
  return process.argv[index + 1];
}

const reportPath = option("--report");
const adjudicationPath = option("--adjudication");
const outputPath = option("--output");
const previewDir = option("--preview-dir");
const report = JSON.parse(await fs.readFile(reportPath, "utf8"));
const csvText = await fs.readFile(adjudicationPath, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Resumen" });
const summary = workbook.worksheets.getItem("Resumen");
const sourceRange = summary.getUsedRange(true);
const rows = sourceRange.rowCount;
const cols = sourceRange.columnCount;
const adjudication = workbook.worksheets.add("Adjudicación");
adjudication.getRangeByIndexes(0, 0, rows, cols).copyFrom(sourceRange, "values");
sourceRange.clear({ applyTo: "all" });
const guide = workbook.worksheets.add("Método");
const metrics = report.model_metrics;
const classification = metrics.classification_report;
const font = "Arial";
const pct = (value) => `${(100 * value).toFixed(1)}%`;

summary.showGridLines = false;
summary.getRange("A2:H19").format.font = { name: font, size: 10, color: "#1F2937" };
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [["Evaluación final de evidencia relacionada"]];
summary.getRange("A2:H2").format = {
  font: { name: font, size: 15, bold: true, color: "#1F2937" },
  rowHeight: 28,
};
summary.getRange("A4:B4").values = [["Métrica", "Resultado"]];
summary.getRange("A5:B13").values = [
  ["Casos del piloto", report.sample_size],
  ["Incluidos después de adjudicación", report.final_included],
  ["Excluidos por contexto insuficiente", report.final_excluded],
  ["Acuerdo bruto entre anotadores", report.raw_stance_agreement_on_jointly_included],
  ["Kappa de Cohen", report.cohen_kappa_on_jointly_included],
  ["Exactitud del modelo", metrics.accuracy],
  ["Macro-F1 de clases observadas", metrics.macro_f1_observed_classes],
  ["IC bootstrap 95% del macro-F1 observado", `${pct(metrics.macro_f1_observed_classes_95_percentile_interval.low)}–${pct(metrics.macro_f1_observed_classes_95_percentile_interval.high)}`],
  ["Macro-F1 de cuatro clases", metrics.macro_f1_four_class],
];
summary.getRange("A4:B4").format = {
  fill: "#243F57",
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
};
summary.getRange("A5:B13").format.font = { name: font, size: 10, color: "#1F2937" };
summary.getRange("B8:B11").format.numberFormat = "0.0%";
summary.getRange("B13").format.numberFormat = "0.0%";
summary.getRange("A5:A13").format.fill = "#EAF0F6";
summary.getRange("A15:E15").values = [["Gold \\ Modelo", "supports", "refutes", "discusses", "unrelated"]];
const matrixRows = metrics.confusion_matrix_label_order.map((label, index) => [label, ...metrics.confusion_matrix[index]]);
summary.getRange("A16:E19").values = matrixRows;
summary.getRange("A15:E15").format = {
  fill: "#243F57",
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
};
summary.getRange("A16:A19").format.fill = "#EAF0F6";
summary.getRange("A16:E19").format.font = { name: font, size: 10, color: "#1F2937" };
summary.getRange("G4:H4").values = [["Hallazgo", "Valor"]];
summary.getRange("G5:H9").values = [
  ["F1 supports", classification.supports["f1-score"]],
  ["Recall supports", classification.supports.recall],
  ["F1 discusses", classification.discusses["f1-score"]],
  ["Recall discusses", classification.discusses.recall],
  ["Error predominante", "8 casos discusses clasificados como supports"],
];
summary.getRange("G4:H4").format = {
  fill: "#243F57",
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
};
summary.getRange("G5:G9").format.fill = "#EAF0F6";
summary.getRange("H5:H8").format.numberFormat = "0.0%";
summary.getRange("G11:H11").merge();
summary.getRange("G11").values = [["Limitación de cobertura"]];
summary.getRange("G11:H11").format = {
  fill: "#F4B183",
  font: { name: font, size: 10, bold: true, color: "#1F2937" },
};
summary.getRange("G12:H14").merge();
summary.getRange("G12").values = [["La muestra final solo contiene supports y discusses. El macro-F1 de cuatro clases incluye ceros para refutes y unrelated; no debe interpretarse como cobertura validada de esas clases."]];
summary.getRange("G12:H14").format = { font: { name: font, size: 10 }, wrapText: true, verticalAlignment: "top" };
summary.getRange("A:A").format.columnWidth = 42;
summary.getRange("B:B").format.columnWidth = 20;
summary.getRange("C:F").format.columnWidth = 14;
summary.getRange("G:G").format.columnWidth = 26;
summary.getRange("H:H").format.columnWidth = 44;

adjudication.showGridLines = false;
adjudication.freezePanes.freezeRows(1);
adjudication.freezePanes.freezeColumns(2);
adjudication.getRange(`A1:Q${rows}`).format.font = { name: font, size: 10, color: "#1F2937" };
adjudication.getRange("A1:Q1").format = {
  fill: "#243F57",
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  rowHeight: 34,
  borders: { preset: "all", style: "thin", color: "#FFFFFF" },
};
adjudication.getRange(`A2:Q${rows}`).format.verticalAlignment = "top";
for (const range of ["B2:F12", "J2:J12", "N2:N12", "Q2:Q12"]) adjudication.getRange(range).format.wrapText = true;
adjudication.getRange(`O2:Q${rows}`).format.fill = "#E2F0D9";
const widths = [20, 42, 18, 36, 48, 40, 22, 18, 16, 38, 22, 18, 16, 38, 28, 18, 42];
for (let i = 0; i < widths.length; i += 1) adjudication.getRangeByIndexes(0, i, rows, 1).format.columnWidth = widths[i];

guide.showGridLines = false;
guide.getRange("A2:B2").merge();
guide.getRange("A2").values = [["Método y alcance"]];
guide.getRange("A2:B2").format = { font: { name: font, size: 15, bold: true, color: "#1F2937" }, rowHeight: 28 };
guide.getRange("A4:B4").values = [["Elemento", "Definición"]];
guide.getRange("A5:B11").values = [
  ["Muestra", "67 evidencias deduplicadas por afirmación y dominio editorial."],
  ["Anotación", "Dos evaluadores independientes con orden aleatorio y sin acceso a la etiqueta del modelo."],
  ["Acuerdo", "Se calcula sobre los 63 casos incluidos por ambos anotadores antes de adjudicar."],
  ["Adjudicación", "Se aplicó la regla conservadora: ante apoyo parcial se usa discusses; títulos no verificables se excluyen por contexto insuficiente."],
  ["Macro-F1 observado", "Promedio de F1 para supports y discusses, las únicas clases presentes en el gold final."],
  ["Macro-F1 de cuatro clases", "Incluye supports, refutes, discusses y unrelated. Refutes y unrelated tienen soporte cero en esta muestra."],
  ["Siguiente validación", "Construir una muestra dirigida con casos refutes y unrelated antes de afirmar desempeño multiclase completo."],
];
guide.getRange("A4:B4").format = { fill: "#243F57", font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
guide.getRange("A5:A11").format.fill = "#DCE6F1";
guide.getRange("A5:B11").format.font = { name: font, size: 10, color: "#1F2937" };
guide.getRange("B5:B11").format.wrapText = true;
guide.getRange("A:A").format.columnWidth = 28;
guide.getRange("B:B").format.columnWidth = 98;
guide.getRange("A4:B11").format.verticalAlignment = "top";

workbook.recalculate();
const summaryCheck = await workbook.inspect({ kind: "table", range: "Resumen!A2:H19", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 8 });
const errorCheck = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
await fs.mkdir(previewDir, { recursive: true });
for (const name of ["Resumen", "Adjudicación", "Método"]) {
  const preview = await workbook.render({ sheetName: name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${name.toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, summaryCheck: summaryCheck.ndjson, errorCheck: errorCheck.ndjson }));
