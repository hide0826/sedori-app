function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
  await sleep(1600);
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
    await sleep(650);
    if (res && res.result === "done") {
      break;
    }
  }
  await sleep(2200);
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

async function captureJob(job, baseUrl, token) {
  const created = await chrome.tabs.create({ url: job.url, active: true });
  await waitTabComplete(created.id);
  await sleep(3500);
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
  let tab = await chrome.tabs.get(created.id);
  if (/login|signin/i.test(tab.url || "")) {
    await chrome.tabs.update(created.id, { url: job.url });
    await waitTabComplete(created.id);
    await sleep(3500);
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
  await sleep(1500);
  await scrollToDescription(created.id);
  tab = await chrome.tabs.get(created.id);
  const desc = await shot(tab);
  await sleep(2000);
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
  await waitTabComplete(created.id);
  await sleep(3000);
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
  const transaction = await shot(tab);
  await postJson(baseUrl, "/result", {
    token,
    id: job.id,
    status: "ok",
    images: [top, desc, transaction],
  });
  try {
    await chrome.tabs.remove(created.id);
  } catch (err) {
    // タブが残っていても撮影結果は届いている
  }
  await sleep(2500);
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
    await postJson(baseUrl, "/result", { token, status: "finished" });
    sendResponse({ ok: true });
  })().catch(async (err) => {
    try {
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
