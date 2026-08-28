import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const csvPath = "output/catalogo_truper_master.csv";
const outputPath = "output/catalogo_truper_master.xlsx";
const previewPath = "tmp/xlsx-build/catalogo_preview.png";

const csvText = (await fs.readFile(csvPath, "utf8")).replace(/^\uFEFF/, "");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Catálogo" });
const sheet = workbook.worksheets.getItem("Catálogo");
const used = sheet.getUsedRange();
const rowCount = used.rowCount;

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
const header = sheet.getRange("A1:I1");
header.format = {
  fill: "#F26722",
  font: { bold: true, color: "#FFFFFF" },
  rowHeight: 28,
  verticalAlignment: "center",
  horizontalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#B84B15" },
};

const dataRange = sheet.getRange(`A2:I${rowCount}`);
dataRange.format = {
  font: { color: "#222222" },
  verticalAlignment: "center",
  borders: { insideHorizontal: { style: "thin", color: "#E6E6E6" } },
};
sheet.getRange(`A2:C${rowCount}`).format.numberFormat = "@";
sheet.getRange(`G2:H${rowCount}`).format.numberFormat = "General";
sheet.getRange(`D2:F${rowCount}`).format.wrapText = false;

const widths = [16, 18, 18, 55, 22, 52, 16, 12, 18];
for (let col = 0; col < widths.length; col += 1) {
  sheet.getRangeByIndexes(0, col, rowCount, 1).format.columnWidth = widths[col];
}
sheet.getRange(`A1:I${rowCount}`).format.rowHeight = 20;
header.format.rowHeight = 30;

const table = sheet.tables.add(`A1:I${rowCount}`, true, "CatalogoTruper");
table.style = "TableStyleMedium2";
table.showFilterButton = true;
table.showBandedRows = true;

sheet.getRange(`I2:I${rowCount}`).conditionalFormats.add("containsText", {
  text: "False",
  format: { fill: "#FFF2CC", font: { color: "#7F6000" } },
});
sheet.getRange(`I2:I${rowCount}`).conditionalFormats.add("containsText", {
  text: "True",
  format: { fill: "#E2F0D9", font: { color: "#375623" } },
});

const preview = await workbook.render({
  sheetName: "Catálogo",
  range: "A1:I18",
  scale: 1.2,
  format: "png",
});
await fs.mkdir("tmp/xlsx-build", { recursive: true });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const inspect = await workbook.inspect({
  kind: "table",
  range: "Catálogo!A1:I8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 9,
});
console.log(inspect.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, previewPath, rowCount }));
