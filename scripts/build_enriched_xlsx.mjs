import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

async function build(csvPath, outputPath, previewPath, tableName) {
  const csvText = (await fs.readFile(csvPath, "utf8")).replace(/^\uFEFF/, "");
  const workbook = await Workbook.fromCSV(csvText, { sheetName: "Catálogo" });
  const sheet = workbook.worksheets.getItem("Catálogo");
  const used = sheet.getUsedRange();
  const rows = used.rowCount;
  const cols = used.columnCount;
  const endColumn = cols === 19 ? "S" : "R";

  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(3);
  const header = sheet.getRange(`A1:${endColumn}1`);
  header.format = {
    fill: "#F26722", font: { bold: true, color: "#FFFFFF" }, rowHeight: 32,
    verticalAlignment: "center", horizontalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: "#B84B15" },
  };
  const data = sheet.getRange(`A2:${endColumn}${rows}`);
  data.format = {
    font: { color: "#222222" }, verticalAlignment: "center",
    borders: { insideHorizontal: { style: "thin", color: "#E8E8E8" } },
  };
  sheet.getRange(`A2:C${rows}`).format.numberFormat = "@";
  sheet.getRange(`I2:L${rows}`).format.numberFormat = "$#,##0.00";
  sheet.getRange(`Q2:Q${rows}`).format.numberFormat = "0";
  sheet.getRange(`D2:H${rows}`).format.wrapText = false;
  const widths = [15, 18, 20, 48, 40, 16, 28, 24, 28, 34, 28, 20, 14, 18, 21, 20, 18, 21, 48];
  for (let col = 0; col < cols; col += 1) {
    sheet.getRangeByIndexes(0, col, rows, 1).format.columnWidth = widths[col];
  }
  sheet.getRange(`A1:${endColumn}${rows}`).format.rowHeight = 20;
  header.format.rowHeight = 32;
  const table = sheet.tables.add(`A1:${endColumn}${rows}`, true, tableName);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  table.showBandedRows = true;
  sheet.getRange(`O2:O${rows}`).conditionalFormats.add("containsText", {
    text: "alta", format: { fill: "#E2F0D9", font: { color: "#375623" } },
  });
  sheet.getRange(`P2:P${rows}`).conditionalFormats.add("containsText", {
    text: "True", format: { fill: "#FCE4D6", font: { color: "#9C0006" } },
  });
  const preview = await workbook.render({ sheetName: "Catálogo", range: `A1:${endColumn}18`, scale: 1.1, format: "png" });
  await fs.mkdir("tmp/xlsx-build", { recursive: true });
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  const inspect = await workbook.inspect({ kind: "table", range: `Catálogo!A1:${endColumn}6`, include: "values,formulas", tableMaxRows: 6, tableMaxCols: cols });
  console.log(inspect.ndjson);
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, summary: "formula errors" });
  console.log(errors.ndjson);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  console.log(JSON.stringify({ outputPath, previewPath, rows, cols }));
}

await build("output/catalogo_truper_enriquecido.csv", "output/catalogo_truper_enriquecido.xlsx", "tmp/xlsx-build/enriquecido_preview.png", "CatalogoEnriquecido");
await build("output/productos_requieren_revision.csv", "output/productos_requieren_revision.xlsx", "tmp/xlsx-build/revision_preview.png", "ProductosRevision");
