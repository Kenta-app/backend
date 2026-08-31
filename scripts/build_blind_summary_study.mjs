import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const payloadPath = process.argv[2];
const outputDir = process.argv[3];
if (!payloadPath || !outputDir) {
  throw new Error("Usage: node build_blind_summary_study.mjs <payload.json> <output-dir>");
}

const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
await fs.mkdir(outputDir, { recursive: true });

const colors = {
  navy: "#17365D",
  blue: "#D9EAF7",
  lightBlue: "#EAF3F8",
  green: "#E2F0D9",
  yellow: "#FFF2CC",
  gray: "#F3F6F8",
  border: "#B7C9D6",
  text: "#1F2937",
  white: "#FFFFFF",
};

const standardBorder = { preset: "outside", style: "thin", color: colors.border };
const choicesWinner = ["A", "B", "Empate"];
const choicesYesNo = ["Sí", "No"];
const choicesStatus = ["No iniciado", "Completado"];

function applyBodyStyle(range) {
  range.format = {
    font: { color: colors.text, name: "Aptos", size: 10 },
    verticalAlignment: "top",
    wrapText: true,
  };
}

function setWidth(sheet, column, px) {
  sheet.getRange(`${column}:${column}`).format.columnWidthPx = px;
}

function addInstructions(workbook, evaluator) {
  const sheet = workbook.worksheets.add("Instrucciones");
  sheet.showGridLines = false;
  sheet.getRange("A1:H1").merge();
  sheet.getRange("A1").values = [["Evaluación humana ciega de resúmenes en español"]];
  sheet.getRange("A1:H1").format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, name: "Aptos Display", size: 16 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange("A1:H1").format.rowHeightPx = 36;

  const rows = [
    ["Evaluadora/evaluador", evaluator],
    ["Objetivo", "Comparar, de forma ciega, dos resúmenes generados para cada artículo. Los nombres de los modelos no aparecen en esta planilla."],
    ["Diseño", "Hay 30 casos. Para cada caso se muestra el artículo fuente y dos salidas anónimas: Sistema A y Sistema B. El orden fue aleatorizado."],
    ["Antes de comenzar", "No busques en internet el artículo ni intentes identificar el modelo. Evalúa solo el artículo y los dos resúmenes que están en la planilla."],
    ["Fidelidad", "Marca A, B o Empate según cuál resumen se apega mejor a los hechos del artículo y evita afirmaciones no sustentadas."],
    ["Fluidez en español", "Marca A, B o Empate según claridad, gramática y naturalidad del español. Una palabra en inglés necesaria, como un nombre propio o sigla, no cuenta como mezcla injustificada."],
    ["Calidad global", "Marca A, B o Empate según cuál sería más útil como resumen informativo del artículo, considerando fidelidad, cobertura y fluidez."],
    ["Mezcla injustificada", "Para cada sistema marca Sí solo si contiene palabras o fragmentos en inglés que no son un nombre propio, sigla, cita o término inevitable."],
    ["Comentarios", "Si detectas un error factual, señala brevemente el hecho del artículo que lo contradice. No nombres modelos en el comentario."],
    ["Estado", "Al completar todas las columnas de evaluación de un caso, cambia Estado a Completado."],
  ];
  sheet.getRange("A3:B12").values = rows;
  sheet.getRange("A3:A12").format = {
    fill: colors.blue,
    font: { bold: true, color: colors.text },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  };
  sheet.getRange("B3:B12").format = {
    fill: colors.white,
    font: { color: colors.text },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  };
  const firstCase = payload.cases[0].case_id;
  const lastCase = payload.cases[payload.cases.length - 1].case_id;
  sheet.getRange("A14:H14").merge();
  sheet.getRange("A14").values = [[`Cómo anotar: abre la hoja ${firstCase}, completa las celdas amarillas y repite hasta ${lastCase}. No modifiques las celdas con el artículo o los resúmenes.`]];
  sheet.getRange("A14:H14").format = {
    fill: colors.yellow,
    font: { bold: true, color: colors.text },
    verticalAlignment: "center",
    wrapText: true,
    borders: standardBorder,
  };
  sheet.getRange("A14:H14").format.rowHeightPx = 34;
  setWidth(sheet, "A", 160);
  setWidth(sheet, "B", 760);
  for (const col of ["C", "D", "E", "F", "G", "H"]) setWidth(sheet, col, 20);
  sheet.getRange("A3:B12").format.rowHeightPx = 48;
  sheet.freezePanes.freezeRows(1);
}

function addCaseSheet(workbook, record, evaluator) {
  const sheet = workbook.worksheets.add(record.case_id);
  sheet.showGridLines = false;
  const mapping = record[`${evaluator.toLowerCase()}_mapping`];
  const summaryA = record.outputs[mapping.A];
  const summaryB = record.outputs[mapping.B];

  const wideRange = (row) => `A${row}:H${row}`;
  const mergeWrite = (row, value, style, heightPx) => {
    sheet.getRange(wideRange(row)).merge();
    sheet.getRange(`A${row}`).values = [[value]];
    sheet.getRange(wideRange(row)).format = style;
    if (heightPx) sheet.getRange(wideRange(row)).format.rowHeightPx = heightPx;
  };

  mergeWrite(1, `Caso ${record.case_id} · Evaluación ciega`, {
    fill: colors.navy,
    font: { bold: true, color: colors.white, name: "Aptos Display", size: 14 },
    verticalAlignment: "center",
  }, 30);
  mergeWrite(3, "Artículo fuente", {
    fill: colors.blue,
    font: { bold: true, color: colors.text, size: 11 },
    verticalAlignment: "center",
    borders: standardBorder,
  }, 24);
  mergeWrite(4, record.title, {
    fill: colors.white,
    font: { bold: true, color: colors.text, size: 11 },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  }, 42);
  mergeWrite(5, `Fuente archivada: ${record.url}`, {
    fill: colors.gray,
    font: { color: "#4B5563", size: 9 },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  }, 28);
  mergeWrite(6, record.article, {
    fill: colors.white,
    font: { color: colors.text, size: 10 },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  }, 460);
  mergeWrite(8, "Sistema A (anónimo)", {
    fill: colors.green,
    font: { bold: true, color: colors.text, size: 11 },
    verticalAlignment: "center",
    borders: standardBorder,
  }, 24);
  mergeWrite(9, summaryA, {
    fill: colors.white,
    font: { color: colors.text, size: 10 },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  }, 90);
  mergeWrite(11, "Sistema B (anónimo)", {
    fill: colors.green,
    font: { bold: true, color: colors.text, size: 11 },
    verticalAlignment: "center",
    borders: standardBorder,
  }, 24);
  mergeWrite(12, summaryB, {
    fill: colors.white,
    font: { color: colors.text, size: 10 },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  }, 90);

  sheet.getRange("A14:D14").merge();
  sheet.getRange("E14:H14").merge();
  sheet.getRange("A14").values = [["Campo de evaluación"]];
  sheet.getRange("E14").values = [["Tu respuesta"]];
  sheet.getRange("A14:D14").format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: standardBorder,
  };
  sheet.getRange("E14:H14").format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: standardBorder,
  };
  const ratingLabels = [
    "Mayor fidelidad al artículo",
    "Mejor fluidez en español",
    "Mejor calidad global",
    "¿Mezcla injustificada en A?",
    "¿Mezcla injustificada en B?",
  ];
  for (let index = 0; index < ratingLabels.length; index += 1) {
    const row = 15 + index;
    sheet.getRange(`A${row}:D${row}`).merge();
    sheet.getRange(`E${row}:H${row}`).merge();
    sheet.getRange(`A${row}`).values = [[ratingLabels[index]]];
    sheet.getRange(`E${row}`).values = [[""]];
  }
  sheet.getRange("A15:D19").format = {
    fill: colors.lightBlue,
    font: { bold: true, color: colors.text },
    verticalAlignment: "center",
    wrapText: true,
    borders: standardBorder,
  };
  sheet.getRange("E15:H19").format = {
    fill: colors.yellow,
    font: { color: colors.text },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: standardBorder,
  };
  sheet.getRange("E15:E17").dataValidation = { rule: { type: "list", values: choicesWinner } };
  sheet.getRange("E18:E19").dataValidation = { rule: { type: "list", values: choicesYesNo } };

  sheet.getRange("A21:H21").merge();
  sheet.getRange("A21").values = [["Comentario o evidencia (opcional; describe errores o motivos, sin nombrar modelos)"]];
  sheet.getRange("A21:H21").format = {
    fill: colors.lightBlue,
    font: { bold: true, color: colors.text },
    verticalAlignment: "center",
    borders: standardBorder,
  };
  sheet.getRange("A22:H25").merge();
  sheet.getRange("A22").values = [[""]];
  sheet.getRange("A22:H25").format = {
    fill: colors.yellow,
    font: { color: colors.text },
    verticalAlignment: "top",
    wrapText: true,
    borders: standardBorder,
  };
  sheet.getRange("A27:D27").merge();
  sheet.getRange("E27:H27").merge();
  sheet.getRange("A27").values = [["Estado"]];
  sheet.getRange("E27").values = [["No iniciado"]];
  sheet.getRange("A27:D27").format = {
    fill: colors.lightBlue,
    font: { bold: true, color: colors.text },
    borders: standardBorder,
  };
  sheet.getRange("E27:H27").format = {
    fill: colors.yellow,
    font: { color: colors.text },
    horizontalAlignment: "center",
    borders: standardBorder,
  };
  sheet.getRange("E27").dataValidation = { rule: { type: "list", values: choicesStatus } };

  for (const col of ["A", "B", "C", "D", "E", "F", "G", "H"]) setWidth(sheet, col, 122);
  sheet.getRange("A14:H19").format.rowHeightPx = 30;
  sheet.getRange("A21:H21").format.rowHeightPx = 24;
  sheet.getRange("A22:H25").format.rowHeightPx = 35;
  sheet.freezePanes.freezeRows(1);
}

async function buildEvaluatorWorkbook(evaluator) {
  const workbook = Workbook.create();
  addInstructions(workbook, evaluator);
  for (const record of payload.cases) addCaseSheet(workbook, record, evaluator);
  const filename = `evaluacion_ciega_resumenes_${evaluator.toLowerCase()}.xlsx`;
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(outputDir, filename));
  return { workbook, filename };
}

async function buildCoordinatorWorkbook() {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Clave privada");
  sheet.showGridLines = false;
  sheet.getRange("A1:H1").merge();
  sheet.getRange("A1").values = [["CLAVE PRIVADA — NO COMPARTIR CON LAS ANOTADORAS"]];
  sheet.getRange("A1:H1").format = {
    fill: "#7F1D1D",
    font: { bold: true, color: colors.white, name: "Aptos Display", size: 14 },
    verticalAlignment: "center",
  };
  sheet.getRange("A1:H1").format.rowHeightPx = 30;
  sheet.getRange("A3:B8").values = [
    ["Población", payload.population],
    ["Método de selección", payload.selection_method],
    ["Tamaño muestral", payload.sample_size],
    ["Semilla de selección", payload.selection_seed],
    ["Método de asignación", payload.assignment_method],
    ["Semilla de asignación", payload.assignment_seed],
  ];
  sheet.getRange("A3:A8").format = { fill: colors.blue, font: { bold: true, color: colors.text }, wrapText: true, borders: standardBorder };
  sheet.getRange("B3:B8").format = { fill: colors.white, font: { color: colors.text }, wrapText: true, borders: standardBorder };
  sheet.getRange("A10:E10").values = [["Caso", "ID fuente", "Sistema A — Salvador", "Sistema A — Jimena", "Orden contrabalanceado"]];
  const rows = payload.cases.map((record) => [
    record.case_id,
    record.source_id,
    record.salvador_mapping.A,
    record.jimena_mapping.A,
    record.salvador_mapping.A !== record.jimena_mapping.A ? "Sí" : "No",
  ]);
  sheet.getRange(`A11:E${10 + rows.length}`).values = rows;
  sheet.getRange("A10:E10").format = {
    fill: "#7F1D1D",
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: standardBorder,
  };
  sheet.getRange(`A11:E${10 + rows.length}`).format = {
    font: { color: colors.text },
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: colors.border },
  };
  setWidth(sheet, "A", 80);
  setWidth(sheet, "B", 85);
  setWidth(sheet, "C", 220);
  setWidth(sheet, "D", 220);
  setWidth(sheet, "E", 160);
  sheet.getRange("A3:B8").format.rowHeightPx = 42;
  sheet.getRange("A10:E10").format.rowHeightPx = 32;
  sheet.freezePanes.freezeRows(10);
  const filename = "clave_privada_evaluacion_ciega_resumenes.xlsx";
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(outputDir, filename));
  return { workbook, filename };
}

const salvador = await buildEvaluatorWorkbook("Salvador");
const jimena = await buildEvaluatorWorkbook("Jimena");
const coordinator = await buildCoordinatorWorkbook();

const firstCase = payload.cases[0].case_id;
const check = await salvador.workbook.inspect({
  kind: "table",
  range: `${firstCase}!A14:H27`,
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 4,
});
console.log(check.ndjson);
for (const item of [salvador, jimena, coordinator]) {
  const errors = await item.workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 50 },
    summary: `formula errors in ${item.filename}`,
  });
  console.log(errors.ndjson);
}

const preview = await salvador.workbook.render({ sheetName: firstCase, range: "A1:H27", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, `preview_${firstCase.toLowerCase()}_salvador.png`), new Uint8Array(await preview.arrayBuffer()));
console.log(`Created ${salvador.filename}, ${jimena.filename}, ${coordinator.filename}`);
