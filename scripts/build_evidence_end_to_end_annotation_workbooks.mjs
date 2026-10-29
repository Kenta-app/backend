import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const args = process.argv.slice(2);
const valueAfter = (flag, fallback = null) => {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : fallback;
};
const inputDir = valueAfter("--input-dir", "output/evidence_end_to_end_2026_10_24");
const outputDir = valueAfter("--output-dir", "outputs/evidence-end-to-end-pilot-2026-10-24");
const previewDir = valueAfter("--preview-dir", "output/evidence_end_to_end_workbook_preview");
const outputStem = valueAfter("--output-stem", "prueba_integral");
const reviewMode = valueAfter("--review-mode", "integral");

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

async function workbookFromCsv(csvPath, sheetName) {
  const csvText = (await fs.readFile(csvPath, "utf8")).replace(/^\uFEFF/, "");
  return Workbook.fromCSV(csvText, { sheetName });
}

function styleSources(sheet) {
  const rows = sheet.getUsedRange(true).rowCount;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(3);
  sheet.getRange(`A1:M${rows}`).format.font = bodyFont;
  sheet.getRange("A1:M1").format = headerFormat;
  sheet.getRange("A1:M1").format.rowHeight = 38;
  sheet.getRange(`A2:M${rows}`).format.verticalAlignment = "top";
  sheet.getRange(`D2:I${rows}`).format.wrapText = true;
  sheet.getRange(`J2:M${rows}`).format.fill = "#FFF4CC";
  sheet.getRange(`A2:C${rows}`).format.fill = "#F2F5F8";
  sheet.getRange(`A2:M${rows}`).format.rowHeight = 78;

  const widths = [8, 19, 13, 42, 18, 18, 36, 48, 38, 23, 18, 14, 34];
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rows, 1).format.columnWidth = width;
  });

  sheet.getRange(`J2:J${rows}`).dataValidation = {
    rule: { type: "list", values: ["evaluable", "unavailable", "insufficient_context"] },
  };
  sheet.getRange(`K2:K${rows}`).dataValidation = {
    rule: { type: "list", values: ["supports", "refutes", "discusses", "unrelated"] },
  };
  sheet.getRange(`L2:L${rows}`).dataValidation = {
    rule: { type: "list", values: ["high", "medium", "low"] },
  };
  sheet.getRange(`K2:K${rows}`).conditionalFormats.addCustom(
    '=AND($J2="evaluable",$K2="")',
    { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
  );
  return rows;
}

function styleCoverage(sheet) {
  const rows = sheet.getUsedRange(true).rowCount;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
  sheet.getRange(`A1:P${rows}`).format.font = bodyFont;
  sheet.getRange("A1:P1").format = headerFormat;
  sheet.getRange("A1:P1").format.rowHeight = 42;
  sheet.getRange(`A2:P${rows}`).format.verticalAlignment = "top";
  sheet.getRange(`D2:J${rows}`).format.wrapText = true;
  sheet.getRange(`L2:P${rows}`).format.fill = "#FFF4CC";
  sheet.getRange(`A2:B${rows}`).format.fill = "#F2F5F8";
  sheet.getRange(`A2:K${rows}`).format.rowHeight = 180;

  const widths = [8, 13, 12, 42, 72, 27, 17, 20, 18, 38, 20, 27, 28, 38, 25, 34];
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rows, 1).format.columnWidth = width;
  });

  sheet.getRange(`L2:L${rows}`).dataValidation = {
    rule: {
      type: "list",
      values: ["sufficient", "partial", "none", "no_evidence_found", "unable_to_assess"],
    },
  };
  sheet.getRange(`M2:M${rows}`).dataValidation = {
    rule: { type: "list", values: ["yes", "no", "unable_to_assess"] },
  };
  sheet.getRange(`O2:O${rows}`).dataValidation = {
    rule: { type: "list", values: ["correct", "incorrect", "unable_to_assess", "not_applicable"] },
  };
  sheet.getRange(`L2:L${rows}`).conditionalFormats.addCustom(
    '=$L2=""',
    { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
  );
  sheet.getRange(`O2:O${rows}`).conditionalFormats.addCustom(
    '=AND($C2="twitter",$O2="")',
    { fill: "#FDE2E2", font: { color: "#9B1C1C", bold: true } },
  );
  return rows;
}

function addGuide(workbook, annotatorLabel) {
  const guide = workbook.worksheets.add("Guía");
  guide.showGridLines = false;
  guide.getRange("A2:F2").merge();
  const focused = reviewMode === "focused-v5";
  const confirmatory = reviewMode === "confirmatory-v6" || reviewMode === "confirmatory-v7";
  const confirmatoryVersion = reviewMode === "confirmatory-v7" ? "v7" : "v6";
  guide.getRange("A2").values = [[focused
    ? `Revisión focalizada v5 — anotador ${annotatorLabel.toUpperCase()}`
    : confirmatory
      ? `Evaluación confirmatoria ${confirmatoryVersion} — anotador ${annotatorLabel.toUpperCase()}`
      : `Prueba integral de evidencia — anotador ${annotatorLabel.toUpperCase()}`]];
  const guideRows = [
    ["Paso o término", "Criterio"],
    [1, focused
      ? "Esta revisión incluye únicamente casos cuyo conjunto de evidencia cambió con retrieval v5. Trabaje primero la hoja Fuentes: contiene solo fuentes independientes nuevas. Abra cada URL y compárela con claim."
      : "Trabaje primero la hoja Fuentes. Abra cada URL y compare su contenido con claim. Si necesita más contexto, consulte el mismo case_id en Cobertura."],
    [2, "Use review_status=evaluable cuando la página permita juzgar la relación. Si no abre, use unavailable. Si abre pero no ofrece texto suficiente, use insufficient_context."],
    [3, "Solo para filas evaluables, complete human_stance y confidence. Escriba en notes el fragmento o razón decisiva."],
    [4, focused
      ? "Después complete Cobertura para todos los casos modificados. Haga una búsqueda web independiente breve por cada claim y registre si el conjunto recuperado omite evidencia relevante."
      : "Después complete Cobertura. Haga una búsqueda web independiente breve por cada claim y registre si falta evidencia relevante."],
    ...(confirmatory ? [[5, "En los seis casos con platform=twitter, evalúe social_context_status a partir de claim, publication_context y la publicación original. Verifique que se atribuya la afirmación al autor correcto y que quote/respuesta no se interprete como si fuera el texto principal."], [6, "No consulte las respuestas del otro anotador ni intente inferir la etiqueta del sistema."]] : [[5, "No consulte las respuestas del otro anotador ni intente inferir la etiqueta del sistema."]]),
    ...(focused ? [["primary_context", "Es la publicación original necesaria para comprender un quote, respuesta o hilo. Puede aportar contexto, pero NO cuenta como corroboración independiente y por ello no aparece en Fuentes para etiquetar postura."]] : []),
    ["supports", "La fuente confirma explícitamente todos los elementos materiales de la proposición."],
    ["refutes", "La fuente niega la proposición, presenta datos incompatibles o establece que la acusación carece de pruebas."],
    ["discusses", "La fuente trata el mismo hecho, pero omite, matiza o cambia un elemento material; también incluye antecedentes, reacciones o estado del proceso."],
    ["unrelated", "Solo comparte una persona, organización o tema general; no aborda el hecho central."],
    ["Regla conservadora", "Ante duda entre supports/refutes y discusses, use discusses. Una coincidencia superficial es unrelated."],
    ["sufficient", "El conjunto recuperado permite evaluar la afirmación y la búsqueda independiente no revela una omisión importante."],
    ["partial", "Hay evidencia útil, pero falta una fuente o perspectiva importante encontrada en la búsqueda independiente."],
    ["none", "El sistema no aportó evidencia útil aunque la búsqueda independiente sí encontró evidencia relevante."],
    ["no_evidence_found", "Ni el sistema ni la búsqueda independiente breve encontraron evidencia periodística relevante."],
    ["unable_to_assess", "No fue posible realizar una comprobación suficiente por acceso, tiempo o ambigüedad."],
    ["missing_relevant_evidence", "Use yes si encontró evidencia relevante no recuperada, no si no encontró omisiones y unable_to_assess si no pudo comprobarlo."],
    ...(confirmatory ? [
      ["correct", "El claim y publication_context identifican correctamente quién formula la afirmación y distinguen el post analizado del contenido citado o respondido."],
      ["incorrect", "La atribución es errónea o falta contexto social esencial, de modo que cambia o distorsiona la interpretación de la afirmación."],
      ["unable_to_assess (social)", "No fue posible verificar la relación entre el post analizado y el quote/respuesta/hilo."],
      ["not_applicable", "Caso no social. Este valor ya está completado y no debe modificarse."],
    ] : []),
  ];
  const guideLastRow = 3 + guideRows.length;
  guide.getRange(`A4:B${guideLastRow}`).values = guideRows;
  guide.getRange("A2:F2").format = {
    font: { name: fontFamily, size: 15, bold: true, color: "#172033" },
    verticalAlignment: "center",
  };
  guide.getRange("A2:F2").format.rowHeight = 28;
  guide.getRange("A4:B4").format = headerFormat;
  guide.getRange(`A5:B${guideLastRow}`).format.font = bodyFont;
  guide.getRange(`A5:B${guideLastRow}`).format.verticalAlignment = "top";
  guide.getRange(`B5:B${guideLastRow}`).format.wrapText = true;
  const finalStepRow = confirmatory ? 10 : 9;
  guide.getRange(`A5:A${finalStepRow}`).format.fill = "#E8F1F8";
  guide.getRange(`A${finalStepRow + 1}:A${guideLastRow}`).format.font = { name: fontFamily, size: 10, bold: true, color: "#172033" };
  guide.getRange("A:A").format.columnWidth = 28;
  guide.getRange("B:B").format.columnWidth = 92;
  guide.getRange(`A4:B${guideLastRow}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
  guide.getRange(`A5:B${guideLastRow}`).format.rowHeight = 42;
  return guide;
}

async function buildAnnotatorWorkbook(annotator) {
  const sourcePath = path.join(inputDir, `annotator_${annotator}_sources.csv`);
  const coveragePath = path.join(inputDir, `annotator_${annotator}_coverage.csv`);
  const workbook = await workbookFromCsv(sourcePath, "Fuentes");
  const coverageBook = await workbookFromCsv(coveragePath, "Cobertura");
  const coverageSource = coverageBook.worksheets.getItem("Cobertura");
  const coverageValues = coverageSource.getUsedRange(true).values;
  const coverage = workbook.worksheets.add("Cobertura");
  coverage.getRange("A1").write(coverageValues);
  const sourceRows = styleSources(workbook.worksheets.getItem("Fuentes"));
  const coverageRows = styleCoverage(coverage);
  addGuide(workbook, annotator);
  workbook.worksheets.getItem("Fuentes").tabColor = "#243B53";
  coverage.tabColor = "#5B7C99";
  workbook.worksheets.getItem("Guía").tabColor = "#A8B5C2";

  workbook.recalculate();
  const sourceCheck = await workbook.inspect({
    kind: "table",
    sheetId: "Fuentes",
    range: `A1:M${Math.min(sourceRows, 5)}`,
    include: "values,formulas",
    tableMaxRows: 5,
    tableMaxCols: 13,
  });
  const coverageCheck = await workbook.inspect({
    kind: "table",
    sheetId: "Cobertura",
    range: `A1:P${Math.min(coverageRows, 5)}`,
    include: "values,formulas",
    tableMaxRows: 5,
    tableMaxCols: 16,
  });
  const errorCheck = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 100 },
    summary: "final formula error scan",
  });

  const annotatorPreviewDir = path.join(previewDir, `annotator_${annotator}`);
  await fs.mkdir(annotatorPreviewDir, { recursive: true });
  const guideLastPreviewRow = reviewMode === "confirmatory-v6" || reviewMode === "confirmatory-v7" ? 26 : 21;
  for (const [sheetName, range] of [["Fuentes", "A1:M6"], ["Cobertura", "A1:P5"], ["Guía", `A1:F${guideLastPreviewRow}`]]) {
    const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
    await fs.writeFile(
      path.join(annotatorPreviewDir, `${sheetName.toLowerCase()}.png`),
      new Uint8Array(await preview.arrayBuffer()),
    );
  }

  await fs.mkdir(outputDir, { recursive: true });
  const outputPath = path.join(outputDir, `anotador_${annotator}_${outputStem}.xlsx`);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  await fs.writeFile(
    `${outputPath}.inspect.ndjson`,
    [sourceCheck.ndjson, coverageCheck.ndjson, errorCheck.ndjson].join("\n"),
    "utf8",
  );
  return { outputPath, sourceRows: sourceRows - 1, coverageRows: coverageRows - 1, errorCheck: errorCheck.ndjson };
}

const results = [];
for (const annotator of ["a", "b"]) {
  results.push(await buildAnnotatorWorkbook(annotator));
}
console.log(JSON.stringify(results));
