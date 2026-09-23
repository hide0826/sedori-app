const node = document.getElementById("hirio-jobs");
if (node && node.textContent) {
  try {
    const data = JSON.parse(node.textContent);
    chrome.runtime.sendMessage({ type: "start", ...data });
    const status = document.getElementById("status");
    if (status) {
      status.textContent = "撮影を開始しました。このタブは開いたままで大丈夫です。";
    }
  } catch (err) {
    const status = document.getElementById("status");
    if (status) {
      status.textContent = "開始できませんでした: " + err;
    }
  }
}
