from __future__ import annotations

import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReceiptMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}
        self.meta: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.by_id[values["id"]] = {"tag": tag, **values}
        if tag == "meta":
            self.meta.append(values)


def test_student_result_receipt_is_mobile_portrait_and_never_contains_login_secret() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    parser = ReceiptMarkupParser()
    parser.feed(html)

    preview = parser.by_id["result-card-preview-image"]
    assert preview["width"] == "1080"
    assert preview["height"] == "1920"
    assert preview["alt"] == "抢选结果凭证预览"
    assert "9:16 手机竖版预览" in html
    assert "请下载并妥善保存「抢选结果凭证」，以便后续核对。" in html
    assert "请注意：最终安排以学院正式发布结果为准。" in html

    card_source = javascript.split("async function createResultCardBlob", 1)[1].split(
        "function resultCardPreviewKey", 1
    )[0]
    assert "canvas.width = 1080" in card_source
    assert "canvas.height = 1920" in card_source
    assert "receipt.verification_code" in card_source
    assert "receipt.verify_url" in card_source
    assert "receipt?.qr_image_url" in javascript
    assert "url.origin === window.location.origin" in javascript
    assert "扫码可核对服务端原始记录" in card_source
    assert "在线核验暂不可用" in card_source
    assert 'context.fillText("核"' not in card_source
    assert "activation_code" not in card_source
    assert "身份证" not in card_source
    assert "证件号" not in card_source


def test_result_preview_is_cached_and_uses_csp_compatible_data_url() -> None:
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    preview_source = javascript.split("function resultCardPreviewKey", 1)[1].split(
        "async function downloadStudentResultCard", 1
    )[0]

    assert "resultCardPreviewPendingKey" in preview_source
    assert "key === studentState.resultCardPreviewKey" in preview_source
    assert "key === studentState.resultCardPreviewPendingKey" in preview_source
    assert "resultCardDataUrl(blob)" in preview_source
    assert "URL.createObjectURL" not in preview_source
    assert "void ensureStudentResultCardPreview(payload)" in javascript
    assert ".result-card-preview__frame" in css
    assert "aspect-ratio: 9 / 16" in css
    assert "object-fit: contain" in css
    assert '.student-body[data-student-view="success"] .student-hero { display: none; }' in css
    assert '.student-body[data-student-view="success"] .result-card-preview { width: min(34vw, 120px);' in css
    assert '.student-body[data-student-view="success"] .success-card__actions { grid-template-columns: 1fr 1fr;' in css


def test_signed_receipt_qr_failure_blocks_preview_cache_and_download() -> None:
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    qr_loader_source = "function resultCardSameOriginImageUrl" + javascript.split(
        "function resultCardSameOriginImageUrl", 1
    )[1].split("function resultCardBlob", 1)[0]
    result_flow_source = "function resultCardPreviewKey" + javascript.split(
        "function resultCardPreviewKey", 1
    )[1].split("function createGroupOption", 1)[0]

    harness = r"""
const assert = require("node:assert/strict");
const window = {
  location: {
    href: "https://class.example/student",
    origin: "https://class.example",
  },
};
let imageRequests = 0;
let imageShouldLoad = true;
class Image {
  set src(_value) {
    imageRequests += 1;
    queueMicrotask(() => imageShouldLoad
      ? this.onload()
      : this.onerror(new Error("network unavailable")));
  }
}

const payload = {
  settings: { activity_id: 9, activity_title: "测试活动" },
  student: { student_no: "20268000008", name: "凭证学生", major_name: "城乡规划" },
  selection: { group_id: 3, group_name: "第三教学组", selected_at: "2026-08-14T12:00:00Z" },
  receipt: {
    verification_code: "ABC-DEF-GHI",
    verify_url: "https://class.example/receipt#token=signed",
    qr_image_url: "https://class.example/api/student/receipt/qr.png",
  },
};
const studentState = {
  payload,
  resultCardInFlight: false,
  resultCardPreviewKey: null,
  resultCardPreviewPendingKey: null,
  resultCardPreviewUrl: null,
};
const studentEls = {
  resultCardPreviewImage: { hidden: false, src: "" },
  resultCardPreviewStatus: { hidden: true, textContent: "" },
  downloadResultCard: { disabled: false, textContent: "下载抢选结果凭证" },
};
let dataUrlCalls = 0;
let objectUrlCalls = 0;
let anchorClicks = 0;
let lastMessage = null;
async function createResultCardBlob(value) {
  await loadResultCardVerificationQr(value);
  return { type: "image/png" };
}
async function resultCardDataUrl(_blob) {
  dataUrlCalls += 1;
  return "data:image/png;base64,unexpected";
}
function showStudentMessage(message, kind) {
  lastMessage = { message, kind };
}
URL.createObjectURL = () => {
  objectUrlCalls += 1;
  return "blob:unexpected";
};
URL.revokeObjectURL = () => {};
const document = {
  createElement(tag) {
    assert.equal(tag, "a");
    return {
      click() { anchorClicks += 1; },
      remove() {},
    };
  },
  body: { append() {} },
};

(async () => {
  for (const incompleteReceipt of [
    null,
    {...payload.receipt, verification_code: ""},
    {...payload.receipt, verify_url: "https://outside.example/receipt#token=signed"},
    {...payload.receipt, qr_image_url: "https://outside.example/qr.png"},
  ]) {
    await assert.rejects(
      loadResultCardVerificationQr({...payload, receipt: incompleteReceipt}),
      /防伪核验信息不完整.*重试/,
    );
  }
  assert.equal(imageRequests, 0, "核验信息缺失或非同源时不应请求二维码");

  const validQr = await loadResultCardVerificationQr(payload);
  assert.ok(validQr instanceof Image, "完整同源核验信息应正常加载二维码");
  assert.equal(imageRequests, 1);

  imageShouldLoad = false;
  await ensureStudentResultCardPreview(payload);
  assert.equal(studentState.resultCardPreviewKey, null, "二维码失败不能写入预览缓存键");
  assert.equal(studentState.resultCardPreviewUrl, null, "二维码失败不能写入预览缓存内容");
  assert.equal(studentState.resultCardPreviewPendingKey, null, "失败后必须释放 pending 状态以便重试");
  assert.equal(dataUrlCalls, 0, "二维码失败不能继续生成可缓存 Data URL");
  assert.equal(studentEls.resultCardPreviewImage.hidden, true);
  assert.match(studentEls.resultCardPreviewStatus.textContent, /防伪二维码.*重试/);

  await downloadStudentResultCard();
  assert.equal(objectUrlCalls, 0, "二维码失败不能生成下载对象 URL");
  assert.equal(anchorClicks, 0, "二维码失败不能触发缺少防伪二维码的下载");
  assert.deepEqual(lastMessage, {
    message: "防伪二维码加载失败，请检查网络后重试",
    kind: "error",
  });
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        ["node", "-e", "\n".join((qr_loader_source, result_flow_source, harness))],
        cwd=ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_public_receipt_page_does_not_persist_or_leak_the_signed_token() -> None:
    html = (ROOT / "web" / "receipt.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "receipt.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "receipt.css").read_text(encoding="utf-8")
    parser = ReceiptMarkupParser()
    parser.feed(html)

    assert any(
        meta.get("name") == "referrer" and meta.get("content") == "no-referrer"
        for meta in parser.meta
    )
    assert parser.by_id["verification-message"]["role"] == "status"
    assert "hidden" in parser.by_id["verification-details"]
    assert "window.location.hash" in javascript
    assert "history.replaceState" in javascript
    assert 'fetch("/api/public/receipts/verify"' in javascript
    assert 'method: "POST"' in javascript
    assert 'body: JSON.stringify({ token })' in javascript
    assert "/api/public/receipts/verify?" not in javascript
    assert "encodeURIComponent(token)" not in javascript
    assert 'credentials: "omit"' in javascript
    assert 'referrerPolicy: "no-referrer"' in javascript
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript
    assert ".innerHTML" not in javascript
    assert "textContent" in javascript
    assert "核验有效" in javascript
    assert "该抢选记录已被撤销" in javascript
    assert "凭证无效或已损坏" in javascript
    assert "aspect-ratio: 3808 / 909" in css
    assert "top: -16.72%" in css
    assert "left: -8.61%" in css
    assert "width: 109.01%" in css
    assert "安徽建筑大学 · 建筑与空间规划学院 制作：Mikutea" in html
