"use strict";

const receiptEls = {
  mark: document.querySelector("#verification-mark"),
  eyebrow: document.querySelector("#verification-eyebrow"),
  title: document.querySelector("#verification-title"),
  message: document.querySelector("#verification-message"),
  details: document.querySelector("#verification-details"),
  activity: document.querySelector("#verification-activity"),
  name: document.querySelector("#verification-name"),
  studentNo: document.querySelector("#verification-student-no"),
  major: document.querySelector("#verification-major"),
  group: document.querySelector("#verification-group"),
  time: document.querySelector("#verification-time"),
  code: document.querySelector("#verification-code"),
  retry: document.querySelector("#verification-retry"),
};

function setReceiptText(element, value) {
  element.textContent = String(value || "—");
}

function formatReceiptTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function renderReceiptState(status, title, message) {
  document.body.dataset.verificationStatus = status;
  const states = {
    loading: ["核验中", "VERIFYING RECEIPT"],
    valid: ["有效", "VERIFIED RECEIPT"],
    revoked: ["已撤销", "RECORD REVOKED"],
    invalid: ["无效", "INVALID RECEIPT"],
    error: ["稍后重试", "VERIFY LATER"],
  };
  const [mark, eyebrow] = states[status] || states.error;
  receiptEls.mark.textContent = mark;
  receiptEls.eyebrow.textContent = eyebrow;
  receiptEls.title.textContent = title;
  receiptEls.message.textContent = message;
}

function renderReceiptDetails(payload) {
  setReceiptText(receiptEls.activity, payload.activity?.title);
  setReceiptText(receiptEls.name, payload.student?.name);
  setReceiptText(receiptEls.studentNo, payload.student?.student_no_masked);
  setReceiptText(receiptEls.major, payload.student?.major_name);
  setReceiptText(receiptEls.group, payload.group?.name);
  setReceiptText(receiptEls.time, formatReceiptTime(payload.selected_at));
  setReceiptText(receiptEls.code, payload.verification_code);
  receiptEls.details.hidden = false;
}

function receiptTokenFromFragment() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
  history.replaceState(null, "", window.location.pathname);
  return /^[A-Za-z0-9._-]{40,512}$/.test(token) ? token : "";
}

const receiptToken = receiptTokenFromFragment();
let receiptVerificationInFlight = false;

function setReceiptRetryVisible(visible) {
  receiptEls.retry.hidden = !visible;
}

async function verifyReceipt() {
  if (!receiptToken) {
    setReceiptRetryVisible(false);
    renderReceiptState("invalid", "凭证链接无效", "链接缺少完整核验信息，请重新扫描原始凭证上的二维码。");
    return;
  }
  if (receiptVerificationInFlight) return;
  receiptVerificationInFlight = true;
  receiptEls.retry.disabled = true;
  setReceiptRetryVisible(false);
  renderReceiptState("loading", "正在核验凭证", "正在读取服务器原始记录，请稍候。");
  try {
    const token = receiptToken;
    const response = await fetch("/api/public/receipts/verify", {
      method: "POST",
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ token }),
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      // The status-specific message below remains useful if a proxy returned HTML.
    }
    if (!response.ok) {
      if (response.status === 400 || response.status === 404) {
        renderReceiptState("invalid", "凭证无效或已损坏", payload.detail || "服务器无法识别该凭证，请核对二维码来源。");
      } else if (response.status === 429) {
        renderReceiptState("error", "核验请求过于频繁", "请稍候片刻后点击“重新核验”。");
        setReceiptRetryVisible(true);
      } else if (response.status >= 500) {
        renderReceiptState("error", "暂时无法完成核验", payload.detail || "服务器暂时不可用，请稍后重试或联系老师核对导出记录。");
        setReceiptRetryVisible(true);
      } else {
        renderReceiptState("invalid", "核验请求无效", payload.detail || "服务器无法处理该凭证，请重新扫描原始凭证上的二维码。");
      }
      return;
    }
    if (payload.revoked) {
      renderReceiptState("revoked", "该抢选记录已被撤销", "此凭证对应的原选择已撤销，不能作为当前有效结果。请以最新系统记录为准。");
      renderReceiptDetails(payload);
      return;
    }
    if (!payload.valid) {
      renderReceiptState("invalid", "未找到匹配的有效记录", "凭证内容与服务器原始记录不一致，请联系老师核对。");
      if (payload.verification_code) setReceiptText(receiptEls.code, payload.verification_code);
      return;
    }
    renderReceiptState("valid", "核验有效", "凭证内容与服务器原始抢选记录一致。");
    renderReceiptDetails(payload);
  } catch (_error) {
    renderReceiptState("error", "网络连接失败", "未能连接核验服务，请检查网络后点击“重新核验”。");
    setReceiptRetryVisible(true);
  } finally {
    receiptVerificationInFlight = false;
    receiptEls.retry.disabled = false;
  }
}

receiptEls.retry.addEventListener("click", () => {
  void verifyReceipt();
});

void verifyReceipt();
