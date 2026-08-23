"use client";

import { DUMMY_REPRICER_CSV, DUMMY_REPRICER_FILENAME } from "./dummyRepricerCsv";

export function DummyRepricerCsvDownload() {
  const handleDownload = () => {
    const blob = new Blob([DUMMY_REPRICER_CSV], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = DUMMY_REPRICER_FILENAME;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <button
      type="button"
      onClick={handleDownload}
      className="font-medium text-[var(--hirio-accent)] underline"
    >
      ダミーCSVをダウンロード
    </button>
  );
}
