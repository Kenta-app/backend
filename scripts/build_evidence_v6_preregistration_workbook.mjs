import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function option(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) throw new Error(`Missing ${name}`);
  return process.argv[index + 1];
}

const readinessPath = option("--readiness");
const outputPath = option("--output");
const previewDir = option("--preview-dir");
const readiness = JSON.parse(await fs.readFile(readinessPath, "utf8"));

const workbook = Workbook.create();
const design = workbook.worksheets.add("Diseño");
const criteria = workbook.worksheets.add("Criterios");
const audit = workbook.worksheets.add("Disponibilidad");
const font = "Arial";
const navy = "#243F57";
const paleBlue = "#EAF0F6";
const paleYellow = "#FFF4CC";
const paleRed = "#FDE2E2";
const paleGreen = "#E2F0D9";
const body = { name: font, size: 10, color: "#1F2937" };
const header = {
  fill: navy,
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};

for (const sheet of [design, criteria, audit]) sheet.showGridLines = false;

design.getRange("A2:F2").merge();
design.getRange("A2").values = [["Prerregistro de la evaluación confirmatoria integral v6"]];
design.getRange("A2:F2").format = { font: { name: font, size: 16, bold: true, color: "#1F2937" }, rowHeight: 30 };
design.getRange("A4:B4").values = [["Elemento", "Decisión congelada"]];
design.getRange("A5:B15").values = [
  ["Protocolo", "evidence-end-to-end-v6-confirmatory-v1"],
  ["Fecha", "2026-10-26 (America/Lima)"],
  ["Muestra", "24 publicaciones nuevas; una por clúster"],
  ["Plataformas", "18 web y 6 X"],
  ["Contexto social", "Al menos 4 casos con quote, respuesta o republicación disponible"],
  ["Diversidad", "Al menos 3 fuentes web y 4 fuentes totales; máximo 8 casos por fuente"],
  ["Fuentes oficiales", "Al menos 2 casos de El Peruano o Agencia Andina"],
  ["Riesgo", "Mínimos: 6 bajos, 6 medios y 4 altos"],
  ["Independencia", "Sin prediction_id ni afirmaciones utilizadas en evaluaciones anteriores"],
  ["Cegamiento", "Dos anotadores, orden independiente y postura del sistema oculta"],
  ["Regla de congelamiento", "No congelar si falla un requisito de composición"],
];
design.getRange("A4:B4").format = header;
design.getRange("A5:A15").format.fill = paleBlue;
design.getRange("A5:B15").format.font = body;
design.getRange("B5:B15").format.wrapText = true;
design.getRange("A:A").format.columnWidth = 27;
design.getRange("B:B").format.columnWidth = 96;

criteria.getRange("A2:D2").merge();
criteria.getRange("A2").values = [["Criterios de aprobación prerregistrados"]];
criteria.getRange("A2:D2").format = { font: { name: font, size: 15, bold: true, color: "#1F2937" }, rowHeight: 28 };
criteria.getRange("A4:C4").values = [["Métrica", "Umbral", "Regla"]];
criteria.getRange("A5:C10").values = [
  ["Contenido devuelto", 0.80, "Sobre las 24 publicaciones"],
  ["Precisión de fuentes independientes", 0.90, "Entre URLs evaluables"],
  ["Cobertura útil", 0.80, "Sufficient o partial en casos evaluables"],
  ["Exactitud de postura", 0.75, "Contra consenso o adjudicación"],
  ["Vacíos falsos", 0.20, "Máximo entre conjuntos sin fuentes"],
  ["Contexto social correcto", 0.80, "Sobre los 6 casos de X"],
];
criteria.getRange("A4:C4").format = header;
criteria.getRange("A5:A10").format.fill = paleBlue;
criteria.getRange("A5:C10").format.font = body;
criteria.getRange("B5:B10").format.numberFormat = "0%";
criteria.getRange("A:A").format.columnWidth = 39;
criteria.getRange("B:B").format.columnWidth = 15;
criteria.getRange("C:C").format.columnWidth = 55;
criteria.getRange("A12:C14").merge();
criteria.getRange("A12").values = [["Si una métrica no tiene denominador, se reportará como no estimable. No se modificarán la política, el prompt ni los umbrales después de abrir los resultados."]];
criteria.getRange("A12:C14").format = { fill: paleYellow, font: body, wrapText: true, verticalAlignment: "top" };

audit.getRange("A2:E2").merge();
audit.getRange("A2").values = [["Disponibilidad antes del congelamiento"]];
audit.getRange("A2:E2").format = { font: { name: font, size: 15, bold: true, color: "#1F2937" }, rowHeight: 28 };
audit.getRange("A4:B4").values = [["Indicador", "Resultado"]];
audit.getRange("A5:B11").values = [
  ["Candidatos elegibles", readiness.eligible_candidate_n],
  ["Grupos únicos", readiness.eligible_unique_group_n],
  ["Web", readiness.platform_counts.web || 0],
  ["X/social", readiness.platform_counts.social || 0],
  ["Con referencia social", readiness.social_reference_context_n],
  ["Fuentes oficiales", readiness.official_source_n],
  ["Listo para congelar", readiness.ready_to_freeze ? "Sí" : "No"],
];
audit.getRange("D4:E4").values = [["Comprobación", "Estado"]];
const checks = Object.entries(readiness.checks);
audit.getRangeByIndexes(4, 3, checks.length, 2).values = checks.map(([name, passed]) => [name, passed ? "Cumple" : "Falta"]);
audit.getRange("A4:B4").format = header;
audit.getRange("D4:E4").format = header;
audit.getRange("A5:A11").format.fill = paleBlue;
audit.getRange(`D5:D${4 + checks.length}`).format.fill = paleBlue;
audit.getRange(`E5:E${4 + checks.length}`).conditionalFormats.addCustom('=$E5="Falta"', { fill: paleRed, font: { color: "#9B1C1C", bold: true } });
audit.getRange(`E5:E${4 + checks.length}`).conditionalFormats.addCustom('=$E5="Cumple"', { fill: paleGreen, font: { color: "#276749" } });
audit.getRange("A5:E20").format.font = body;
audit.getRange("A:A").format.columnWidth = 30;
audit.getRange("B:B").format.columnWidth = 18;
audit.getRange("C:C").format.columnWidth = 4;
audit.getRange("D:D").format.columnWidth = 38;
audit.getRange("E:E").format.columnWidth = 16;
audit.getRange("A14:B18").merge();
audit.getRange("A14").values = [["La muestra permanece sin congelar. La población disponible no incluye X, riesgo alto, diversidad editorial ni fuentes oficiales suficientes. Se debe ampliar la ingesta y repetir la auditoría."]];
audit.getRange("A14:B18").format = { fill: paleYellow, font: body, wrapText: true, verticalAlignment: "top" };

workbook.recalculate();
const designCheck = await workbook.inspect({ kind: "table", range: "Diseño!A2:B15", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 3 });
const auditCheck = await workbook.inspect({ kind: "table", range: "Disponibilidad!A2:E20", include: "values,formulas", tableMaxRows: 22, tableMaxCols: 6 });
const formulaErrors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });

await fs.mkdir(previewDir, { recursive: true });
const previewRanges = { "Diseño": "A1:F16", "Criterios": "A1:D15", "Disponibilidad": "A1:E19" };
for (const name of ["Diseño", "Criterios", "Disponibilidad"]) {
  const preview = await workbook.render({ sheetName: name, range: previewRanges[name], scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${name.toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, designCheck: designCheck.ndjson, auditCheck: auditCheck.ndjson, formulaErrors: formulaErrors.ndjson }));
