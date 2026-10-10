function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 撮影開始前のウィンドウ状態（終わったら戻す） */
let previousWindowState = null;
let captureWindowId = null;

function waitTabComplete(tabId) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, 20000);
    function listener(id, info) {
      if (id === tabId && info.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function pageState(tabId) {
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const url = location.href || "";
      const text = document.body ? document.body.innerText.slice(0, 4000) : "";
      const password = !!document.querySelector("input[type='password']");
      const loginUrl = /login|signin/i.test(url);
      return {
        url,
        login: loginUrl || password,
        hasTransactionButton: text.includes("取引画面を表示する"),
        hasPurchaseDate: text.includes("購入日時") || text.includes("商品ID"),
      };
    },
  });
  return (res && res.result) || { url: "", login: false };
}

/**
 * ウィンドウが最大化でなければ最大化する（真正の全画面にはしない）。
 * captureVisibleTab は表示中の領域だけ撮るため、小さい窓だと画像が欠ける。
 * 外周（タイトルバー等）が残る「最大化」で画面いっぱいにする。
 */
async function ensureMaximizedWindow(windowId) {
  const win = await chrome.windows.get(windowId);
  captureWindowId = windowId;
  if (previousWindowState === null) {
    previousWindowState = win.state || "normal";
  }
  // fullscreen のままなら一度戻してから最大化（外周が見える状態にする）
  if (win.state === "fullscreen") {
    await chrome.windows.update(windowId, { state: "maximized", focused: true });
    await sleep(700);
    return;
  }
  if (win.state !== "maximized") {
    await chrome.windows.update(windowId, { state: "maximized", focused: true });
    await sleep(700);
  } else {
    await chrome.windows.update(windowId, { focused: true });
    await sleep(200);
  }
}

/** 情報撮影が終わったら、使っていたChromeを最小化する。 */
async function minimizeCaptureWindow() {
  if (captureWindowId == null) {
    return;
  }
  try {
    await chrome.windows.update(captureWindowId, { state: "minimized" });
  } catch (err) {
    // ウィンドウが閉じ済み
  }
  previousWindowState = null;
  captureWindowId = null;
}

/**
 * 商品画像が読み込まれるまで待つ（早すぎて真っ白／欠ける対策）。
 */
async function waitForProductImages(tabId) {
  for (let i = 0; i < 20; i += 1) {
    try {
      const [res] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          const imgs = [...document.querySelectorAll("img")];
          let ready = 0;
          let pending = 0;
          for (const img of imgs) {
            const src = img.currentSrc || img.src || "";
            if (!src || src.startsWith("data:")) {
              continue;
            }
            if (!img.complete) {
              pending += 1;
              continue;
            }
            const w = img.naturalWidth || 0;
            const h = img.naturalHeight || 0;
            if (w >= 60 && h >= 60) {
              ready += 1;
            }
          }
          return { ready, pending };
        },
      });
      const result = (res && res.result) || { ready: 0, pending: 1 };
      // 大きめの画像が1枚以上あり、読み込み待ちがなければOK
      if (result.ready >= 1 && result.pending === 0) {
        await sleep(700);
        return;
      }
    } catch (err) {
      // ナビ中など
    }
    await sleep(400);
  }
  // タイムアウト時も少し待ってから撮る
  await sleep(1200);
}

async function shotWithDebugger(tabId) {
  await chrome.debugger.attach({ tabId }, "1.3");
  try {
    const result = await chrome.debugger.sendCommand({ tabId }, "Page.captureScreenshot", {
      format: "png",
    });
    return result.data;
  } finally {
    try {
      await chrome.debugger.detach({ tabId });
    } catch (err) {
      // すでに外れている
    }
  }
}

async function shot(tab) {
  await ensureMaximizedWindow(tab.windowId);
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
  // フォーカス・描画が落ち着くまで待つ
  await sleep(1400);
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
    const comma = dataUrl.indexOf(",");
    return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
  } catch (err) {
    return await shotWithDebugger(tab.id);
  }
}

async function scrollToDescription(tabId) {
  for (let step = 0; step < 8; step += 1) {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const nodes = document.querySelectorAll("h1,h2,h3,section,div,span,p");
        for (const el of nodes) {
          const text = (el.innerText || "").trim();
          if (text.startsWith("商品の説明")) {
            const top = el.getBoundingClientRect().top;
            if (top < 90) {
              return "done";
            }
            window.scrollBy(0, Math.min(320, Math.max(120, top - 80)));
            return "moved";
          }
        }
        window.scrollBy(0, 280);
        return "moved";
      },
    });
    await sleep(450);
    if (res && res.result === "done") {
      break;
    }
  }
  await sleep(1400);
}

async function openTransaction(tabId) {
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const els = [...document.querySelectorAll("a,button")];
      const btn = els.find((el) => (el.innerText || "").includes("取引画面を表示する"));
      if (!btn) {
        return false;
      }
      btn.scrollIntoView({ block: "center" });
      btn.click();
      return true;
    },
  });
  return !!(res && res.result);
}

async function postJson(baseUrl, path, body) {
  await fetch(baseUrl + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function waitControl(baseUrl, token) {
  for (;;) {
    const res = await fetch(baseUrl + "/control?token=" + encodeURIComponent(token));
    const data = await res.json();
    if (data.action === "continue") {
      return true;
    }
    if (data.action === "abort") {
      return false;
    }
    await sleep(500);
  }
}

async function ensureLoggedIn(tabId, baseUrl, token, jobId) {
  let state = await pageState(tabId);
  if (!state.login) {
    return true;
  }
  await postJson(baseUrl, "/result", {
    token,
    id: jobId,
    status: "login",
  });
  const go = await waitControl(baseUrl, token);
  if (!go) {
    return false;
  }
  await sleep(800);
  state = await pageState(tabId);
  return !state.login;
}

async function preparePageForShot(tabId) {
  await waitTabComplete(tabId);
  // ページ表示直後の白飛び対策：固定待ち＋画像読み込み待ち（少し短縮）
  await sleep(2800);
  await waitForProductImages(tabId);
}

/**
 * 取引画面の DOM から出品者名を取る（スクショ外・OCR欠落対策）。
 * 画面をスクロールしなくても、DOM 上にあれば取得できる。
 */
async function extractSellerNameFromDom(tabId) {
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const skipFrags = [
          "出品者情報",
          "本人確認済",
          "本人確認",
          "24時間",
          "評価を変更",
          "取引が完了",
          "取引完了",
          "コピーする",
          "ゆうゆうメルカリ便",
          "ゆうパケット",
          "でお届け",
          "らくらくメルカリ便",
          "専用資材",
          "匿名配送",
          "出品者負担",
          "出品者レベル",
          "送料",
          "サイズ",
          "厚さ",
          "重さ",
          "kg以内",
          "cm以内",
        ];
        const junkOnly = new Set(["済", "円", "税込", "レベル", "プラス"]);
        const deliveryMarkers = [
          "ゆうパケット",
          "メルカリ便",
          "専用資材",
          "匿名配送",
          "でお届け",
          "サイズ",
          "厚さ",
          "kg以内",
          "cm以内",
          "送料込み",
          "出品者負担",
        ];
        const clean = (raw) => {
          const text = String(raw || "").trim();
          if (!text || /^[¥￥]/.test(text)) {
            return "";
          }
          // 配送行は断片（「プラス」等）を拾わない
          if (deliveryMarkers.some((m) => text.includes(m))) {
            return "";
          }
          let parts = [text];
          for (const frag of skipFrags) {
            const next = [];
            for (const p of parts) {
              next.push(...p.split(frag));
            }
            parts = next;
          }
          for (const part of parts) {
            const cand = part.replace(/\s+/g, " ").trim().replace(/^[:：・|\-\s]+|[:：・|\-\s]+$/g, "");
            if (!cand || junkOnly.has(cand) || cand.length > 40) {
              continue;
            }
            if (/^m\d{8,16}$/i.test(cand) || /^[0-9,]+$/.test(cand)) {
              continue;
            }
            return cand;
          }
          return "";
        };
        const lines = (document.body && document.body.innerText ? document.body.innerText : "")
          .split(/\n+/)
          .map((s) => s.trim())
          .filter(Boolean);
        for (let i = 0; i < lines.length; i += 1) {
          if (!lines[i].includes("出品者情報")) {
            continue;
          }
          const same = clean(lines[i].split("出品者情報").slice(1).join("出品者情報"));
          if (same) {
            return same;
          }
          for (let j = i + 1; j < Math.min(i + 8, lines.length); j += 1) {
            const cand = clean(lines[j]);
            if (cand) {
              return cand;
            }
          }
        }
        for (let i = 0; i < lines.length; i += 1) {
          if (!lines[i].includes("本人確認")) {
            continue;
          }
          for (let j = Math.max(0, i - 4); j < i; j += 1) {
            const cand = clean(lines[j]);
            if (cand) {
              return cand;
            }
          }
        }
        return "";
      },
    });
    return (res && res.result) || "";
  } catch (err) {
    return "";
  }
}

async function captureJob(job, baseUrl, token) {
  const created = await chrome.tabs.create({ url: job.url, active: true });
  await preparePageForShot(created.id);
  let tab = await chrome.tabs.get(created.id);
  await ensureMaximizedWindow(tab.windowId);

  const loggedIn = await ensureLoggedIn(created.id, baseUrl, token, job.id);
  if (!loggedIn) {
    await postJson(baseUrl, "/result", {
      token,
      id: job.id,
      status: "stopped",
      message: "ログイン待ちを中止しました。",
    });
    return false;
  }
  tab = await chrome.tabs.get(created.id);
  if (/login|signin/i.test(tab.url || "")) {
    await chrome.tabs.update(created.id, { url: job.url });
    await preparePageForShot(created.id);
    if (!(await ensureLoggedIn(created.id, baseUrl, token, job.id))) {
      await postJson(baseUrl, "/result", {
        token,
        id: job.id,
        status: "stopped",
        message: "ログインできませんでした。",
      });
      return false;
    }
  }
  tab = await chrome.tabs.get(created.id);
  const top = await shot(tab);
  await sleep(900);
  await scrollToDescription(created.id);
  tab = await chrome.tabs.get(created.id);
  const desc = await shot(tab);
  await sleep(1200);
  const clicked = await openTransaction(created.id);
  if (!clicked) {
    await postJson(baseUrl, "/result", {
      token,
      id: job.id,
      status: "error",
      message: "取引画面を表示するボタンがありません。",
    });
    return true;
  }
  await preparePageForShot(created.id);
  if (!(await ensureLoggedIn(created.id, baseUrl, token, job.id))) {
    await postJson(baseUrl, "/result", {
      token,
      id: job.id,
      status: "stopped",
      message: "ログイン待ちを中止しました。",
    });
    return false;
  }
  const after = await pageState(created.id);
  if (!after.hasPurchaseDate) {
    await postJson(baseUrl, "/result", {
      token,
      id: job.id,
      status: "error",
      message: "取引画面を開けませんでした。",
    });
    return true;
  }
  tab = await chrome.tabs.get(created.id);
  const sellerName = await extractSellerNameFromDom(created.id);
  const transaction = await shot(tab);
  await postJson(baseUrl, "/result", {
    token,
    id: job.id,
    status: "ok",
    images: [top, desc, transaction],
    seller_name: sellerName || "",
  });
  try {
    await chrome.tabs.remove(created.id);
  } catch (err) {
    // タブが残っていても撮影結果は届いている
  }
  await sleep(1600);
  return true;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "start") {
    return;
  }
  const baseUrl = message.baseUrl;
  const token = message.token;
  const jobs = message.jobs || [];
  (async () => {
    previousWindowState = null;
    captureWindowId = null;
    await postJson(baseUrl, "/hello", { token });
    for (const job of jobs) {
      try {
        const keepGoing = await captureJob(job, baseUrl, token);
        if (!keepGoing) {
          break;
        }
      } catch (err) {
        await postJson(baseUrl, "/result", {
          token,
          id: job.id,
          status: "error",
          message: String(err && err.message ? err.message : err),
        });
      }
    }
    await minimizeCaptureWindow();
    await postJson(baseUrl, "/result", { token, status: "finished" });
    sendResponse({ ok: true });
  })().catch(async (err) => {
    try {
      await minimizeCaptureWindow();
      await postJson(baseUrl, "/result", {
        token,
        status: "error",
        message: String(err),
      });
    } catch (postErr) {
      // HIRIO側が先に閉じた
    }
    sendResponse({ ok: false, error: String(err) });
  });
  return true;
});
