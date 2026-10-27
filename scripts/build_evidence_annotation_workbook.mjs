import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const args = process.argv.slice(2);
const valueAfter = (flag) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : null;
};
const inputPath = valueAfter("--input");
const outputPath = valueAfter("--output") || "outputs/evidence-annotation-pilot-2026-10-21/plantilla_anotacion_evidencia.xlsx";
const previewDir = valueAfter("--preview-dir") || "output/evidence_annotation_workbook_preview";

let workbook;
let annotation;
if (inputPath) {
  const csvText = await fs.readFile(inputPath, "utf8");
  workbook = await Workbook.fromCSV(csvText.replace(/^\uFEFF/, ""), { sheetName: "Anotación" });
  annotation = workbook.worksheets.getItem("Anotación");
} else {
  workbook = Workbook.create();
  annotation = workbook.worksheets.add("Anotación");
  annotation.getRange("A1:K1").values = [[
    "order", "evidence_id", "claim", "source_name", "source_title",
    "evidence_excerpt", "source_url", "review_status", "human_stance",
    "confidence", "notes",
  ]];
  annotation.getRange("A2:K26").values = Array.from({ length: 25 }, () => Array(11).fill(""));
}
const annotationEndRow = annotation.getUsedRange(true).rowCount;

const guide = workbook.worksheets.add("Guía");
guide.getRange("A2:F2").merge();
guide.getRange("A2").values = [["Anotación de evidencia relacionada"]];
guide.getRange("A4:B13").values = [
  ["Paso", "Instrucción"],
  [1, "Abra la URL y contraste su contenido con la afirmación central."],
  [2, "Complete review_status. Use include solo si hay contexto suficiente."],
  [3, "Si usa include, seleccione una postura y un nivel de confianza."],
  [4, "Anote la razón o el fragmento decisivo de forma breve."],
  ["", ""],
  ["review_status", "include | exclude_unavailable | exclude_insufficient_context"],
  ["supports", "La fuente confirma explícitamente la misma afirmación."],
  ["refutes", "La fuente contradice explícitamente la misma afirmación."],
  ["discusses", "Trata el tema, pero no confirma ni contradice la proposición completa."],
];
guide.getRange("A14:B19").values = [
  ["unrelated", "No trata la misma afirmación o la coincidencia es superficial."],
  ["Regla conservadora", "Ante duda entre supports/refutes y discusses, use discusses."],
  ["Elementos materiales", "Revise actor, acción o hecho, objeto, tiempo, lugar y cantidad cuando correspondan."],
  ["supports", "Exige que la fuente confirme todos los elementos necesarios de la proposición completa."],
  ["discusses", "Úselo si falta, cambia o se matiza un elemento material, o si solo hay antecedentes, reacciones o estado del proceso."],
  ["Muestra dirigida", "Este lote calibra clases escasas y casos frontera. No representa la prevalencia natural ni una evaluación confirmatoria independiente."],
];

annotation.showGridLines = false;
guide.showGridLines = false;
annotation.freezePanes.freezeRows(1);
annotation.freezePanes.freezeColumns(2);

const font = { name: "Arial", size: 10, color: "#172033" };
annotation.getRange(`A1:K${annotationEndRow}`).format.font = font;
annotation.getRange("A1:K1").format = {
  fill: "#243B53",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "inside", style: "thin", color: "#FFFFFF" },
};
annotation.getRange("A1:K1").format.rowHeight = 34;
annotation.getRange(`A2:K${annotationEndRow}`).format.verticalAlignment = "top";
annotation.getRange(`C2:G${annotationEndRow}`).format.wrapText = true;
annotation.getRange(`K2:K${annotationEndRow}`).format.wrapText = true;
annotation.getRange(`H2:K${annotationEndRow}`).format.fill = "#FFF4CC";
annotation.getRange(`A2:B${annotationEndRow}`).format.fill = "#F2F5F8";
annotation.getRange("A:A").format.columnWidth = 8;
annotation.getRange("B:B").format.columnWidth = 22;
annotation.getRange("C:C").format.columnWidth = 42;
annotation.getRange("D:D").format.columnWidth = 20;
annotation.getRange("E:E").format.columnWidth = 34;
annotation.getRange("F:F").format.columnWidth = 48;
annotation.getRange("G:G").format.columnWidth = 38;
annotation.getRange("H:H").format.columnWidth = 28;
annotation.getRange("I:I").format.columnWidth = 18;
annotation.getRange("J:J").format.columnWidth = 14;
annotation.getRange("K:K").format.columnWidth = 34;
annotation.getRange(`H2:H${annotationEndRow}`).dataValidation = {
  rule: { type: "list", values: ["include", "exclude_unavailable", "exclude_insufficient_context"] },
};
annotation.getRange(`I2:I${annotationEndRow}`).dataValidation = {
  rule: { type: "list", values: ["supports", "refutes", "discusses", "unrelated"] },
};
annotation.getRange(`J2:J${annotationEndRow}`).dataValidation = {
  rule: { type: "list", values: ["high", "medium", "low"] },
};
annotation.getRange(`I2:I${annotationEndRow}`).conditionalFormats.addCustom(
  '=AND($H2="include",$I2="")',
  { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
);

guide.getRange("A2:F2").format = {
  font: { name: "Arial", size: 15, bold: true, color: "#172033" },
  verticalAlignment: "center",
};
guide.getRange("A2:F2").format.rowHeight = 28;
guide.getRange("A4:B4").format = {
  fill: "#243B53",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
guide.getRange("A5:B19").format.font = font;
guide.getRange("A5:B19").format.verticalAlignment = "top";
guide.getRange("B5:B19").format.wrapText = true;
guide.getRange("A5:A7").format.fill = "#E8F1F8";
guide.getRange("A9:A19").format.font = { name: "Arial", size: 10, bold: true, color: "#172033" };
guide.getRange("A:A").format.columnWidth = 24;
guide.getRange("B:B").format.columnWidth = 78;
guide.getRange("A4:B19").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };

workbook.recalculate();
const tableCheck = await workbook.inspect({
  kind: "table",
  sheetId: "Anotación",
  range: "A1:K8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 11,
});
const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
await fs.mkdir(previewDir, { recursive: true });
for (const sheetName of ["Anotación", "Guía"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName.toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, tableCheck: tableCheck.ndjson, errorCheck: errorCheck.ndjson }));
