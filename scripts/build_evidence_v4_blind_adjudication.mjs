import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const args = process.argv.slice(2);
const valueAfter = (flag) => {
  const index = args.indexOf(flag);
  if (index < 0 || index + 1 >= args.length) throw new Error(`Missing ${flag}`);
  return args[index + 1];
};

const inputDir = valueAfter("--input-dir");
const outputPath = valueAfter("--output");
const previewDir = valueAfter("--preview-dir");
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

async function csvValues(fileName) {
  const text = (await fs.readFile(path.join(inputDir, fileName), "utf8")).replace(/^\uFEFF/, "");
  const temporary = await Workbook.fromCSV(text, { sheetName: "Data" });
  return temporary.worksheets.getItem("Data").getUsedRange(true).values;
}

function selectColumns(values, columns) {
  const headers = values[0].map(String);
  const indexes = columns.map((column) => {
    const index = headers.indexOf(column);
    if (index < 0) throw new Error(`Missing column ${column}`);
    return index;
  });
  return [columns, ...values.slice(1).map((row) => indexes.map((index) => row[index]))];
}

function addSheet(workbook, name, values, widths, wrapColumns) {
  const sheet = workbook.worksheets.add(name);
  sheet.getRange("A1").write(values);
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
  const rows = values.length;
  const columns = values[0].length;
  sheet.getRangeByIndexes(0, 0, rows, columns).format.font = bodyFont;
  sheet.getRangeByIndexes(0, 0, 1, columns).format = headerFormat;
  sheet.getRangeByIndexes(0, 0, 1, columns).format.rowHeight = 38;
  if (rows > 1) {
    sheet.getRangeByIndexes(1, 0, rows - 1, columns).format.verticalAlignment = "top";
    sheet.getRangeByIndexes(1, 0, rows - 1, columns).format.rowHeight = 76;
  }
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rows, 1).format.columnWidth = width;
  });
  wrapColumns.forEach((index) => {
    if (rows > 1) sheet.getRangeByIndexes(1, index, rows - 1, 1).format.wrapText = true;
  });
  return sheet;
}

const sourceRaw = await csvValues("source_disagreements.csv");
const coverageRaw = await csvValues("coverage_disagreements.csv");
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
const sourceValues = selectColumns(sourceRaw, sourceColumns);
const coverageValues = selectColumns(coverageRaw, coverageColumns);

const workbook = Workbook.create();
const source = addSheet(
  workbook,
  "Fuentes",
  sourceValues,
  [18, 13, 38, 20, 34, 48, 38, 20, 18, 34, 20, 18, 34, 24, 18, 44],
  [2, 4, 5, 6, 9, 12, 15],
);
const coverage = addSheet(
  workbook,
  "Cobertura",
  coverageValues,
  [13, 40, 18, 38, 18, 24, 20, 38, 34, 24, 20, 38, 34, 26, 20, 38, 44],
  [1, 3, 7, 8, 11, 12, 15, 16],
);

const sourceLastRow = sourceValues.length;
const coverageLastRow = coverageValues.length;
source.getRange(`N2:P${sourceLastRow}`).format.fill = "#FFF4CC";
source.getRange(`N2:N${sourceLastRow}`).dataValidation = {
  rule: { type: "list", values: ["evaluable", "unavailable", "insufficient_context"] },
};
source.getRange(`O2:O${sourceLastRow}`).dataValidation = {
  rule: { type: "list", values: ["supports", "refutes", "discusses", "unrelated"] },
};
coverage.getRange(`N2:Q${coverageLastRow}`).format.fill = "#FFF4CC";
coverage.getRange(`N2:N${coverageLastRow}`).dataValidation = {
  rule: { type: "list", values: ["sufficient", "partial", "none", "no_evidence_found", "unable_to_assess"] },
};
coverage.getRange(`O2:O${coverageLastRow}`).dataValidation = {
  rule: { type: "list", values: ["yes", "no", "unable_to_assess"] },
};

const guide = workbook.worksheets.add("Guía");
guide.showGridLines = false;
guide.getRange("A2:F2").merge();
guide.getRange("A2").values = [["Adjudicación ciega de evidencia v4"]];
guide.getRange("A2:F2").format = {
  font: { name: fontFamily, size: 15, bold: true, color: "#172033" },
  verticalAlignment: "center",
};
guide.getRange("A4:B12").values = [
  ["Paso", "Instrucción"],
  [1, "Revise únicamente las filas incluidas. Son desacuerdos de los dos anotadores."],
  [2, "Abra las URLs cuando sea necesario y aplique las definiciones de la guía original."],
  [3, "Complete solo las columnas amarillas final_* y adjudication_rationale."],
  [4, "No consulte evidence_annotation_key.csv, model_stance ni resultados del sistema antes de decidir."],
  ["Fuentes", "Defina final_status. Si es evaluable, seleccione final_stance y explique el elemento material decisivo."],
  ["Cobertura", "Seleccione final_coverage y final_missing. Si final_missing=yes, registre una URL representativa."],
  ["Independencia", "Un tercero es preferible. Si adjudica uno de los anotadores, debe revisar nuevamente la evidencia y justificar la decisión."],
  ["Entrega", "Devuelva este libro completo para calcular las métricas finales prerregistradas."],
];
guide.getRange("A4:B4").format = headerFormat;
guide.getRange("A5:B12").format.font = bodyFont;
guide.getRange("A5:B12").format.verticalAlignment = "top";
guide.getRange("B5:B12").format.wrapText = true;
guide.getRange("A:A").format.columnWidth = 24;
guide.getRange("B:B").format.columnWidth = 96;
guide.getRange("A5:B12").format.rowHeight = 42;
source.tabColor = "#243B53";
coverage.tabColor = "#5B7C99";
guide.tabColor = "#A8B5C2";

workbook.recalculate();
const checks = [];
checks.push((await workbook.inspect({
  kind: "table", sheetId: "Fuentes", range: `A1:P${sourceLastRow}`,
  include: "values,formulas", tableMaxRows: 8, tableMaxCols: 16,
})).ndjson);
checks.push((await workbook.inspect({
  kind: "table", sheetId: "Cobertura", range: `A1:Q${coverageLastRow}`,
  include: "values,formulas", tableMaxRows: 8, tableMaxCols: 17,
})).ndjson);
checks.push((await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
})).ndjson);

await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range, fileName] of [
  ["Fuentes", `A1:P${sourceLastRow}`, "fuentes.png"],
  ["Cobertura", `A1:Q${coverageLastRow}`, "cobertura.png"],
  ["Guía", "A1:F12", "guia.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(`${outputPath}.inspect.ndjson`, checks.join("\n"), "utf8");
console.log(JSON.stringify({
  outputPath,
  sourceDisagreements: sourceLastRow - 1,
  coverageDisagreements: coverageLastRow - 1,
}));
