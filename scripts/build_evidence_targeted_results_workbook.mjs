import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) throw new Error(`Missing ${name}`);
  return process.argv[index + 1];
}

const agreementReportPath = option("--agreement-report");
const finalReportPath = option("--final-report");
const finalCsvPath = option("--final-csv");
const adjudicationCsvPath = option("--adjudication-csv");
const outputPath = option("--output");
const previewDir = option("--preview-dir");

const agreement = JSON.parse(await fs.readFile(agreementReportPath, "utf8"));
const finalReport = JSON.parse(await fs.readFile(finalReportPath, "utf8"));
const finalCsv = (await fs.readFile(finalCsvPath, "utf8")).replace(/^\uFEFF/, "");
const adjudicationCsv = (await fs.readFile(adjudicationCsvPath, "utf8")).replace(/^\uFEFF/, "");

const workbook = await Workbook.fromCSV("Métrica,Resultado\n", { sheetName: "Resumen" });
const summary = workbook.worksheets.getItem("Resumen");
const finalBook = await Workbook.fromCSV(finalCsv, { sheetName: "Resultado final" });
const finalSource = finalBook.worksheets.getItem("Resultado final").getUsedRange(true);
const finalSheet = workbook.worksheets.add("Resultado final");
finalSheet.getRangeByIndexes(0, 0, finalSource.rowCount, finalSource.columnCount).copyFrom(finalSource, "values");
const adjudicationBook = await Workbook.fromCSV(adjudicationCsv, { sheetName: "Adjudicacion" });
const adjudicationSource = adjudicationBook.worksheets.getItem("Adjudicacion").getUsedRange(true);
const adjudicationSheet = workbook.worksheets.add("Adjudicacion");
adjudicationSheet.getRangeByIndexes(0, 0, adjudicationSource.rowCount, adjudicationSource.columnCount).copyFrom(adjudicationSource, "values");
const method = workbook.worksheets.add("Metodo");
const font = "Arial";
const navy = "#243F57";
const paleBlue = "#EAF0F6";
const paleGreen = "#E2F0D9";
const paleOrange = "#FCE4D6";

summary.showGridLines = false;
summary.getRange("A1:B1").clear({ applyTo: "all" });
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [["Desafío dirigido: acuerdo y adjudicación final"]];
summary.getRange("A2:H2").format = { font: { name: font, size: 16, bold: true, color: "#1F2937" }, rowHeight: 30 };
summary.getRange("A4:B4").values = [["Métrica", "Resultado"]];
summary.getRange("A5:B12").values = [
  ["Casos evaluados", agreement.sample_size],
  ["Cobertura de ambos anotadores", agreement.jointly_included],
  ["Acuerdo de estado", agreement.status_agreement],
  ["Acuerdo bruto de postura", agreement.stance_raw_agreement],
  ["Kappa de Cohen", agreement.cohen_kappa],
  ["Acuerdos directos", finalReport.agreement_decisions],
  ["Casos adjudicados", finalReport.adjudicated_decisions],
  ["Coincidencia con referencia histórica", finalReport.historical_reference_match_rate],
];
summary.getRange("D4:E4").values = [["Etiqueta final", "Casos"]];
summary.getRange("D5:E8").values = [
  ["supports", finalReport.final_label_counts.supports ?? 0],
  ["refutes", finalReport.final_label_counts.refutes ?? 0],
  ["discusses", finalReport.final_label_counts.discusses ?? 0],
  ["unrelated", finalReport.final_label_counts.unrelated ?? 0],
];
summary.getRange("G4:H4").values = [["Lectura", "Conclusión"]];
summary.getRange("G5:H8").values = [
  ["Fiabilidad", "κ = 0.842: acuerdo fuerte entre anotadores en una muestra deliberadamente difícil."],
  ["Frontera crítica", "Los cuatro desacuerdos se concentraron en refutes/discusses y supports/discusses."],
  ["Resultado", "La adjudicación final conserva 12 refutes, 8 discusses y 20 unrelated; no quedan supports."],
  ["Uso correcto", "Esta muestra sirve para calibración y regresión, no para estimar prevalencia ni desempeño confirmatorio independiente."],
];
for (const header of ["A4:B4", "D4:E4", "G4:H4"]) {
  summary.getRange(header).format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
}
summary.getRange("A5:A12").format.fill = paleBlue;
summary.getRange("D5:D8").format.fill = paleBlue;
summary.getRange("G5:G8").format.fill = paleBlue;
summary.getRange("A4:H12").format.font = { name: font, size: 10, color: "#1F2937" };
summary.getRange("B7:B8").format.numberFormat = "0.0%";
summary.getRange("B9").format.numberFormat = "0.000";
summary.getRange("B12").format.numberFormat = "0.0%";
summary.getRange("G5:H8").format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 40;
summary.getRange("B:B").format.columnWidth = 18;
summary.getRange("C:C").format.columnWidth = 4;
summary.getRange("D:D").format.columnWidth = 20;
summary.getRange("E:E").format.columnWidth = 12;
summary.getRange("F:F").format.columnWidth = 4;
summary.getRange("G:G").format.columnWidth = 24;
summary.getRange("H:H").format.columnWidth = 62;
summary.getRange("A4:H12").format.verticalAlignment = "top";

const finalRows = finalSheet.getUsedRange(true).rowCount;
finalSheet.showGridLines = false;
finalSheet.freezePanes.freezeRows(1);
finalSheet.freezePanes.freezeColumns(2);
finalSheet.getRange(`A1:J${finalRows}`).format.font = { name: font, size: 10, color: "#1F2937" };
finalSheet.getRange("A1:J1").format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, wrapText: true, horizontalAlignment: "center", verticalAlignment: "center", rowHeight: 34 };
finalSheet.getRange(`B2:F${finalRows}`).format.wrapText = true;
finalSheet.getRange(`J2:J${finalRows}`).format.wrapText = true;
finalSheet.getRange(`A2:J${finalRows}`).format.verticalAlignment = "top";
finalSheet.getRange(`G2:J${finalRows}`).format.fill = paleGreen;
const finalWidths = [20, 44, 18, 40, 54, 40, 18, 18, 18, 58];
for (let i = 0; i < finalWidths.length; i += 1) finalSheet.getRangeByIndexes(0, i, finalRows, 1).format.columnWidth = finalWidths[i];

const adjRows = adjudicationSheet.getUsedRange(true).rowCount;
adjudicationSheet.showGridLines = false;
adjudicationSheet.freezePanes.freezeRows(1);
adjudicationSheet.freezePanes.freezeColumns(2);
adjudicationSheet.getRange(`A1:Q${adjRows}`).format.font = { name: font, size: 10, color: "#1F2937" };
adjudicationSheet.getRange("A1:Q1").format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, wrapText: true, horizontalAlignment: "center", verticalAlignment: "center", rowHeight: 34 };
adjudicationSheet.getRange(`B2:F${adjRows}`).format.wrapText = true;
adjudicationSheet.getRange(`J2:J${adjRows}`).format.wrapText = true;
adjudicationSheet.getRange(`N2:N${adjRows}`).format.wrapText = true;
adjudicationSheet.getRange(`Q2:Q${adjRows}`).format.wrapText = true;
adjudicationSheet.getRange(`O2:Q${adjRows}`).format.fill = paleGreen;
adjudicationSheet.getRange(`A2:Q${adjRows}`).format.verticalAlignment = "top";
const adjWidths = [20, 44, 18, 38, 52, 38, 20, 18, 16, 42, 20, 18, 16, 42, 18, 18, 62];
for (let i = 0; i < adjWidths.length; i += 1) adjudicationSheet.getRangeByIndexes(0, i, adjRows, 1).format.columnWidth = adjWidths[i];

method.showGridLines = false;
method.getRange("A2:B2").merge();
method.getRange("A2").values = [["Método, decisiones y límites de interpretación"]];
method.getRange("A2:B2").format = { font: { name: font, size: 15, bold: true, color: "#1F2937" }, rowHeight: 28 };
method.getRange("A4:B4").values = [["Elemento", "Definición"]];
method.getRange("A5:B13").values = [
  ["Diseño", "40 casos dirigidos: 13 refutes históricos, 20 unrelated y 7 casos de frontera discusses. La composición fue intencional."],
  ["Protocolo", "evidence-policy-2026-10-22-v2. Supports exige confirmar todos los elementos materiales; el apoyo parcial se clasifica como discusses."],
  ["Independencia", "Los dos anotadores trabajaron por separado y sin usar la etiqueta histórica como criterio de decisión."],
  ["Acuerdo", "El acuerdo bruto y κ se calcularon sobre los 40 casos incluidos por ambos anotadores, antes de adjudicar."],
  ["Adjudicación", "Se resolvieron cuatro conflictos usando la relación semántica entre afirmación y evidencia, no por mayoría ni por preferencia personal."],
  ["Tres refutes", "Las fuentes negaban la premisa material de que existían pruebas de fraude, corrupción o actas fantasma."],
  ["Un discusses", "El Peruano confirmó un corte del conteo oficial, pero el fragmento no probó una actualización continua literalmente en tiempo real."],
  ["Referencia histórica", "La coincidencia de 97.5% es una comprobación de consistencia/regresión. No es exactitud independiente porque esas etiquetas se usaron para construir la muestra."],
  ["Uso en tesis", "Reportar este bloque como validación dirigida de clases difíciles y de la regla supports→discusses; reservar desempeño confirmatorio para una muestra nueva y ciega."],
];
method.getRange("A4:B4").format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
method.getRange("A5:A13").format.fill = paleBlue;
method.getRange("B12:B13").format.fill = paleOrange;
method.getRange("A5:B13").format = { font: { name: font, size: 10, color: "#1F2937" }, verticalAlignment: "top" };
method.getRange("B5:B13").format.wrapText = true;
method.getRange("A:A").format.columnWidth = 28;
method.getRange("B:B").format.columnWidth = 105;

workbook.recalculate();
const summaryCheck = await workbook.inspect({ kind: "table", range: "Resumen!A2:H12", include: "values,formulas", tableMaxRows: 14, tableMaxCols: 8 });
const adjudicationCheck = await workbook.inspect({ kind: "table", range: `Adjudicacion!A1:Q${adjRows}`, include: "values,formulas", tableMaxRows: 8, tableMaxCols: 17 });
const errorCheck = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });

await fs.mkdir(previewDir, { recursive: true });
for (const name of ["Resumen", "Adjudicacion", "Metodo"]) {
  const preview = await workbook.render({ sheetName: name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${name.toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, summaryCheck: summaryCheck.ndjson, adjudicationCheck: adjudicationCheck.ndjson, errorCheck: errorCheck.ndjson }));
