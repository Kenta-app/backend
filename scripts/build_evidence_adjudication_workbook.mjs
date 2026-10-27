import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) {
    throw new Error(`Missing required option ${name}`);
  }
  return process.argv[index + 1];
}

const inputPath = option("--input");
const outputPath = option("--output");
const previewDir = option("--preview-dir");

const csvText = await fs.readFile(inputPath, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Adjudicación" });
const sheet = workbook.worksheets.getItem("Adjudicación");
const guide = workbook.worksheets.add("Guía");
const font = "Arial";
const lastRow = Math.max(2, sheet.getUsedRange(true).rowCount);

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(2);
sheet.getRange(`A1:Q${lastRow}`).format.font = { name: font, size: 10, color: "#1F2937" };
sheet.getRange("A1:Q1").format = {
  fill: "#243F57",
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  rowHeight: 34,
  borders: { preset: "all", style: "thin", color: "#FFFFFF" },
};
sheet.getRange(`A2:Q${lastRow}`).format.verticalAlignment = "top";
sheet.getRange(`B2:F${lastRow}`).format.wrapText = true;
sheet.getRange(`J2:J${lastRow}`).format.wrapText = true;
sheet.getRange(`N2:N${lastRow}`).format.wrapText = true;
sheet.getRange(`Q2:Q${lastRow}`).format.wrapText = true;
sheet.getRange(`O2:Q${lastRow}`).format.fill = "#FFF2CC";
sheet.getRange(`O2:O${lastRow}`).dataValidation = {
  rule: { type: "list", values: ["include", "exclude_unavailable", "exclude_insufficient_context"] },
};
sheet.getRange(`P2:P${lastRow}`).dataValidation = {
  rule: { type: "list", values: ["supports", "refutes", "discusses", "unrelated"] },
};

const widths = [20, 42, 18, 36, 48, 40, 22, 18, 16, 38, 22, 18, 16, 38, 28, 18, 42];
for (let i = 0; i < widths.length; i += 1) {
  sheet.getRangeByIndexes(0, i, lastRow, 1).format.columnWidth = widths[i];
}

guide.showGridLines = false;
guide.getRange("A2:B2").merge();
guide.getRange("A2").values = [["Adjudicación de evidencia relacionada"]];
guide.getRange("A2:B2").format = {
  font: { name: font, size: 15, bold: true, color: "#1F2937" },
  rowHeight: 28,
};
guide.getRange("A4:B4").values = [["Paso", "Instrucción"]];
guide.getRange("A4:B4").format = {
  fill: "#243F57",
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
};
guide.getRange("A5:B11").values = [
  [1, "Revise la afirmación, el fragmento, la URL y las razones de ambos anotadores."],
  [2, "Complete final_status. Use include solo si existe contexto suficiente."],
  [3, "Si final_status es include, seleccione una final_stance."],
  [4, "Si el caso se excluye, deje final_stance vacía."],
  [5, "Registre una justificación breve en rationale."],
  ["Criterio", "supports confirma; refutes contradice; discusses trata el tema sin resolver la afirmación; unrelated no trata la misma afirmación."],
  ["Regla", "Decida con base en la evidencia. No elija por mayoría ni por la etiqueta del modelo."],
];
guide.getRange("A5:B11").format.font = { name: font, size: 10, color: "#1F2937" };
guide.getRange("A5:A11").format.fill = "#DCE6F1";
guide.getRange("B5:B11").format.wrapText = true;
guide.getRange("A:A").format.columnWidth = 18;
guide.getRange("B:B").format.columnWidth = 92;
guide.getRange("A4:B11").format.verticalAlignment = "top";

workbook.recalculate();
const tableCheck = await workbook.inspect({
  kind: "table",
  range: `Adjudicación!A1:Q${Math.min(lastRow, 12)}`,
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 17,
});
const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

await fs.mkdir(previewDir, { recursive: true });
for (const name of ["Adjudicación", "Guía"]) {
  const preview = await workbook.render({ sheetName: name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${name.toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, lastRow, tableCheck: tableCheck.ndjson, errorCheck: errorCheck.ndjson }));
