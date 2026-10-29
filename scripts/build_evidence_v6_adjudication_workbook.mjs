import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const args = process.argv.slice(2);
const valueAfter = (flag, fallback = null) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : fallback;
};

const annotatorAPath = valueAfter(
  "--annotator-a",
  "C:/Users/sdiaz/Downloads/anotador_a_prueba_confirmatoria_v6_completado.xlsx",
);
const annotatorBPath = valueAfter(
  "--annotator-b",
  "C:/Users/sdiaz/Downloads/anotador_b_prueba_confirmatoria_v6_completado.xlsx",
);
const evidenceKeyPath = valueAfter(
  "--evidence-key",
  "output/evidence_confirmatory_v6_2026_10_26/evidence_annotation_key.csv",
);
const outputPath = valueAfter(
  "--output",
  "outputs/evidence-confirmatory-v6-adjudication-2026-10-27/adjudicacion_v6_ciega.xlsx",
);
const previewDir = valueAfter(
  "--preview-dir",
  "output/evidence_confirmatory_v6_adjudication_preview",
);

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

function rowsFromValues(values) {
  const headers = values[0].map((value) => String(value ?? "").trim());
  return values.slice(1).map((row) => Object.fromEntries(
    headers.map((header, index) => [header, row[index] ?? ""]),
  ));
}

async function readWorkbookSheet(filePath, sheetName) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(filePath));
  return rowsFromValues(workbook.worksheets.getItem(sheetName).getUsedRange(true).values);
}

async function readCsv(csvPath, sheetName) {
  const csvText = (await fs.readFile(csvPath, "utf8")).replace(/^\uFEFF/, "");
  const workbook = await Workbook.fromCSV(csvText, { sheetName });
  return rowsFromValues(workbook.worksheets.getItem(sheetName).getUsedRange(true).values);
}

function norm(value) {
  return String(value ?? "").trim().toLowerCase();
}

function seededShuffle(rows, seed) {
  let state = seed >>> 0;
  const random = () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
  const result = [...rows];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    [result[index], result[target]] = [result[target], result[index]];
  }
  return result;
}

const [aSources, bSources, aCoverage, bCoverage, evidenceKey] = await Promise.all([
  readWorkbookSheet(annotatorAPath, "Fuentes"),
  readWorkbookSheet(annotatorBPath, "Fuentes"),
  readWorkbookSheet(annotatorAPath, "Cobertura"),
  readWorkbookSheet(annotatorBPath, "Cobertura"),
  readCsv(evidenceKeyPath, "EvidenceKey"),
]);

const byId = (rows, field) => new Map(rows.map((row) => [String(row[field]), row]));
const aSourceById = byId(aSources, "evidence_id");
const bSourceById = byId(bSources, "evidence_id");
const aCoverageById = byId(aCoverage, "case_id");
const bCoverageById = byId(bCoverage, "case_id");
const keyByEvidenceId = byId(evidenceKey, "evidence_id");

let stanceDisagreements = [];
for (const [evidenceId, rowA] of aSourceById.entries()) {
  const rowB = bSourceById.get(evidenceId);
  if (!rowB) throw new Error(`Missing evidence_id ${evidenceId} in annotator B workbook.`);
  const reviewDiffers = norm(rowA.review_status) !== norm(rowB.review_status);
  const stanceDiffers = norm(rowA.human_stance) !== norm(rowB.human_stance);
  if (reviewDiffers || stanceDiffers) {
    const key = keyByEvidenceId.get(evidenceId);
    stanceDisagreements.push({
      evidence_id: evidenceId,
      case_id: rowA.case_id,
      claim: rowA.claim,
      source_name: rowA.source_name,
      source_title: rowA.source_title,
      evidence_excerpt: rowA.evidence_excerpt,
      source_url: rowA.source_url,
      publication_context: key?.publication_context ?? "",
      annotator_a_stance: rowA.human_stance,
      annotator_a_notes: rowA.notes,
      annotator_b_stance: rowB.human_stance,
      annotator_b_notes: rowB.notes,
      final_stance: "",
      adjudication_reason: "",
    });
  }
}
stanceDisagreements = seededShuffle(stanceDisagreements, 20261027)
  .map((row, index) => ({ order: index + 1, ...row }));

const evidenceByCase = new Map();
for (const row of evidenceKey) {
  const caseId = String(row.case_id);
  if (!evidenceByCase.has(caseId)) evidenceByCase.set(caseId, []);
  evidenceByCase.get(caseId).push(row);
}

function evidenceSummary(caseId) {
  return (evidenceByCase.get(String(caseId)) ?? []).map((row, index) => [
    `${index + 1}. ${row.source_name}: ${row.source_title}`,
    row.evidence_excerpt,
    row.source_url,
  ].filter(Boolean).join(" — ")).join("\n\n");
}

let coverageDisagreements = [];
for (const [caseId, rowA] of aCoverageById.entries()) {
  const rowB = bCoverageById.get(caseId);
  if (!rowB) throw new Error(`Missing case_id ${caseId} in annotator B workbook.`);
  const disputedFields = [];
  if (norm(rowA.coverage_status) !== norm(rowB.coverage_status)) disputedFields.push("coverage_status");
  if (norm(rowA.missing_relevant_evidence) !== norm(rowB.missing_relevant_evidence)) {
    disputedFields.push("missing_relevant_evidence");
  }
  for (const disputedField of disputedFields) {
    coverageDisagreements.push({
      case_id: caseId,
      disputed_field: disputedField,
      platform: rowA.platform,
      claim: rowA.claim,
      publication_context: rowA.publication_context,
      original_source: rowA.original_source,
      original_url: rowA.original_url,
      returned_source_count: Number(rowA.returned_source_count || 0),
      retrieved_evidence: evidenceSummary(caseId),
      annotator_a_value: rowA[disputedField],
      annotator_a_missing_source_url: rowA.missing_source_url,
      annotator_a_notes: rowA.notes,
      annotator_b_value: rowB[disputedField],
      annotator_b_missing_source_url: rowB.missing_source_url,
      annotator_b_notes: rowB.notes,
      final_value: "",
      adjudication_reason: "",
    });
  }
}
coverageDisagreements = seededShuffle(coverageDisagreements, 20261028)
  .map((row, index) => ({ order: index + 1, ...row }));

if (stanceDisagreements.length !== 7 || coverageDisagreements.length !== 2) {
  throw new Error(
    `Expected 7 stance and 2 coverage disagreements; found ${stanceDisagreements.length} and ${coverageDisagreements.length}.`,
  );
}

const workbook = Workbook.create();
const stanceSheet = workbook.worksheets.add("Postura");
const coverageSheet = workbook.worksheets.add("Cobertura");
const guideSheet = workbook.worksheets.add("Guía");

const stanceHeaders = [
  "order", "evidence_id", "case_id", "claim", "publication_context", "source_name",
  "source_title", "evidence_excerpt", "source_url", "annotator_a_stance",
  "annotator_a_notes", "annotator_b_stance", "annotator_b_notes", "final_stance",
  "adjudication_reason",
];
stanceSheet.getRange("A1").write([
  stanceHeaders,
  ...stanceDisagreements.map((row) => stanceHeaders.map((header) => row[header])),
]);

const coverageHeaders = [
  "order", "case_id", "disputed_field", "platform", "claim", "publication_context",
  "original_source", "original_url", "returned_source_count", "retrieved_evidence",
  "annotator_a_value", "annotator_a_missing_source_url", "annotator_a_notes",
  "annotator_b_value", "annotator_b_missing_source_url", "annotator_b_notes",
  "final_value", "adjudication_reason",
];
coverageSheet.getRange("A1").write([
  coverageHeaders,
  ...coverageDisagreements.map((row) => coverageHeaders.map((header) => row[header])),
]);

function styleDataSheet(sheet, lastColumn, rows, editableColumns, wrapColumns, widths) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(3);
  sheet.getRange(`A1:${lastColumn}${rows}`).format.font = bodyFont;
  sheet.getRange(`A1:${lastColumn}1`).format = headerFormat;
  sheet.getRange(`A1:${lastColumn}1`).format.rowHeight = 42;
  sheet.getRange(`A2:${lastColumn}${rows}`).format.verticalAlignment = "top";
  for (const column of wrapColumns) sheet.getRange(`${column}2:${column}${rows}`).format.wrapText = true;
  for (const column of editableColumns) sheet.getRange(`${column}2:${column}${rows}`).format.fill = "#FFF4CC";
  sheet.getRange(`A2:C${rows}`).format.fill = "#F2F5F8";
  sheet.getRange(`A2:${lastColumn}${rows}`).format.rowHeight = 150;
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rows, 1).format.columnWidth = width;
  });
}

styleDataSheet(
  stanceSheet,
  "O",
  stanceDisagreements.length + 1,
  ["N", "O"],
  ["D", "E", "G", "H", "I", "K", "M", "O"],
  [8, 18, 13, 40, 54, 18, 34, 48, 36, 20, 38, 20, 38, 20, 40],
);
stanceSheet.getRange(`N2:N${stanceDisagreements.length + 1}`).dataValidation = {
  rule: { type: "list", values: ["supports", "refutes", "discusses", "unrelated"] },
};
stanceSheet.getRange(`N2:N${stanceDisagreements.length + 1}`).conditionalFormats.addCustom(
  '=$N2=""',
  { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
);
stanceSheet.getRange(`O2:O${stanceDisagreements.length + 1}`).conditionalFormats.addCustom(
  '=AND($N2<>"",$O2="")',
  { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
);

styleDataSheet(
  coverageSheet,
  "R",
  coverageDisagreements.length + 1,
  ["Q", "R"],
  ["E", "F", "H", "J", "L", "M", "O", "P", "R"],
  [8, 13, 29, 12, 40, 54, 18, 36, 17, 54, 22, 34, 38, 22, 34, 38, 27, 40],
);
coverageSheet.getRange("Q2").dataValidation = {
  rule: { type: "list", values: ["yes", "no", "unable_to_assess"] },
};
coverageSheet.getRange("Q3").dataValidation = {
  rule: {
    type: "list",
    values: ["sufficient", "partial", "none", "no_evidence_found", "unable_to_assess"],
  },
};
for (let row = 2; row <= coverageDisagreements.length + 1; row += 1) {
  const disputedField = coverageSheet.getRange(`C${row}`).values[0][0];
  coverageSheet.getRange(`Q${row}`).dataValidation = disputedField === "coverage_status"
    ? { rule: { type: "list", values: ["sufficient", "partial", "none", "no_evidence_found", "unable_to_assess"] } }
    : { rule: { type: "list", values: ["yes", "no", "unable_to_assess"] } };
}
coverageSheet.getRange(`Q2:Q${coverageDisagreements.length + 1}`).conditionalFormats.addCustom(
  '=$Q2=""',
  { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
);
coverageSheet.getRange(`R2:R${coverageDisagreements.length + 1}`).conditionalFormats.addCustom(
  '=AND($Q2<>"",$R2="")',
  { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
);

guideSheet.showGridLines = false;
guideSheet.getRange("A2:F2").merge();
guideSheet.getRange("A2").values = [["Adjudicación ciega de evidencia v6"]];
guideSheet.getRange("A2:F2").format = {
  font: { name: fontFamily, size: 15, bold: true, color: "#172033" },
  verticalAlignment: "center",
};
guideSheet.getRange("A2:F2").format.rowHeight = 28;
const guideRows = [
  ["Paso o término", "Criterio"],
  [1, "Complete únicamente las celdas amarillas de Postura y Cobertura. No consulte la salida del sistema ni los archivos de clave."],
  [2, "Lea claim, contexto, extracto y URL. Elija una decisión propia; no use mayoría ni promedie las respuestas de A y B."],
  [3, "Registre una justificación breve que identifique el elemento material decisivo. Las nueve decisiones requieren razón."],
  [4, "En Cobertura, final_value debe usar las opciones correspondientes a disputed_field. Revise también la evidencia recuperada y cualquier URL faltante propuesta."],
  ["supports", "La fuente confirma explícitamente todos los elementos materiales de la proposición."],
  ["refutes", "La fuente niega la proposición, presenta datos incompatibles o establece que la acusación carece de pruebas."],
  ["discusses", "La fuente trata el mismo hecho, pero omite, matiza o cambia al menos un elemento material."],
  ["unrelated", "Solo comparte una persona, organización o tema general; no aborda el hecho central."],
  ["Regla conservadora", "Ante duda entre supports/refutes y discusses, use discusses. Una coincidencia superficial es unrelated."],
  ["sufficient", "El conjunto recuperado permite evaluar la afirmación y no se identifica una omisión importante."],
  ["partial", "Hay evidencia útil, pero falta una fuente o perspectiva importante."],
  ["none", "El sistema no aportó evidencia útil aunque sí existe evidencia relevante."],
  ["no_evidence_found", "Ni el sistema ni la búsqueda independiente encontraron evidencia periodística relevante."],
  ["missing_relevant_evidence", "Use yes si existe evidencia relevante no recuperada; no si no hay omisión; unable_to_assess si no pudo comprobarlo."],
];
guideSheet.getRange(`A4:B${3 + guideRows.length}`).values = guideRows;
guideSheet.getRange("A4:B4").format = headerFormat;
guideSheet.getRange(`A5:B${3 + guideRows.length}`).format.font = bodyFont;
guideSheet.getRange(`A5:B${3 + guideRows.length}`).format.verticalAlignment = "top";
guideSheet.getRange(`B5:B${3 + guideRows.length}`).format.wrapText = true;
guideSheet.getRange("A5:A8").format.fill = "#E8F1F8";
guideSheet.getRange(`A9:A${3 + guideRows.length}`).format.font = {
  name: fontFamily, size: 10, bold: true, color: "#172033",
};
guideSheet.getRange("A:A").format.columnWidth = 28;
guideSheet.getRange("B:B").format.columnWidth = 92;
guideSheet.getRange(`A4:B${3 + guideRows.length}`).format.borders = {
  preset: "outside", style: "thin", color: "#CBD5E1",
};
guideSheet.getRange(`A5:B${3 + guideRows.length}`).format.rowHeight = 42;

stanceSheet.tabColor = "#243B53";
coverageSheet.tabColor = "#5B7C99";
guideSheet.tabColor = "#A8B5C2";

workbook.recalculate();
const stanceCheck = await workbook.inspect({
  kind: "table", sheetId: "Postura", range: "A1:O8", include: "values,formulas",
  tableMaxRows: 8, tableMaxCols: 15,
});
const coverageCheck = await workbook.inspect({
  kind: "table", sheetId: "Cobertura", range: "A1:R3", include: "values,formulas",
  tableMaxRows: 3, tableMaxCols: 18,
});
const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range] of [
  ["Postura", "A1:O8"],
  ["Cobertura", "A1:R3"],
  ["Guía", "A1:F18"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(
    path.join(previewDir, `${sheetName.toLowerCase()}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(
  `${outputPath}.inspect.ndjson`,
  [stanceCheck.ndjson, coverageCheck.ndjson, errorCheck.ndjson].join("\n"),
  "utf8",
);

console.log(JSON.stringify({
  outputPath,
  stanceDisagreements: stanceDisagreements.length,
  coverageDisagreements: coverageDisagreements.length,
  errorCheck: errorCheck.ndjson,
}));
