from __future__ import annotations

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
    assert "payload?.receipt?.qr_image_url" in javascript
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
