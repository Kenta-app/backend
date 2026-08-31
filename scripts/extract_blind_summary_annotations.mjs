import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [inputPath, evaluator, outputPath, casePrefix = "C"] = process.argv.slice(2);
if (!inputPath || !evaluator || !outputPath) {
  throw new Error("Usage: node extract_blind_summary_annotations.mjs <input.xlsx> <evaluator> <output.json> [case-prefix]");
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const cases = [];
for (let number = 1; number <= 30; number += 1) {
  const caseId = `${casePrefix}${String(number).padStart(2, "0")}`;
  const sheet = workbook.worksheets.getItem(caseId);
  const ratings = sheet.getRange("E15:E19").values.map((row) => row[0] ?? "");
  const comment = sheet.getRange("A22").values[0][0] ?? "";
  const status = sheet.getRange("E27").values[0][0] ?? "";
  cases.push({
    case_id: caseId,
    title: sheet.getRange("A4").values[0][0] ?? "",
    fidelity: ratings[0],
    fluency: ratings[1],
    overall: ratings[2],
    english_a: ratings[3],
    english_b: ratings[4],
    comment,
    status,
  });
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(outputPath, JSON.stringify({ evaluator, cases }, null, 2), "utf8");
console.log(JSON.stringify({ evaluator, cases: cases.length, completed: cases.filter((item) => item.status === "Completado").length }));
