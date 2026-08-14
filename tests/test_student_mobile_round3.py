from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


class _StudentDomParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}
        self._active_id: str | None = None
        self.text_by_id: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        element_id = attributes.get("id")
        if element_id:
            self.by_id[element_id] = {"tag": tag, **attributes}
            self._active_id = element_id

    def handle_endtag(self, tag: str) -> None:
        self._active_id = None

    def handle_data(self, data: str) -> None:
        if self._active_id:
            self.text_by_id[self._active_id] = self.text_by_id.get(self._active_id, "") + data


def _student_dom() -> tuple[_StudentDomParser, str]:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    parser = _StudentDomParser()
    parser.feed(html)
    return parser, html


def test_student_login_fields_have_strict_mobile_and_accessibility_contracts() -> None:
    parser, _ = _student_dom()

    student_no = parser.by_id["student-no"]
    assert student_no["inputmode"] == "numeric"
    assert student_no["minlength"] == student_no["maxlength"] == "11"
    assert student_no["pattern"] == "[0-9]{11}"
    assert student_no["autocomplete"] == "username"
    assert student_no["autocorrect"] == "off"
    assert "student-no-help" in student_no["aria-describedby"]
    assert "student-no-error" in student_no["aria-describedby"]

    name = parser.by_id["student-name"]
    assert name["maxlength"] == "40"
    assert "A-Za-z" in name["pattern"]
    assert "·•・" in name["pattern"]
    assert name["autocomplete"] == "name"
    assert "student-name-help" in name["aria-describedby"]
    assert "student-name-error" in name["aria-describedby"]

    activation = parser.by_id["activation-code"]
    assert activation["minlength"] == activation["maxlength"] == "6"
    assert activation["pattern"] == "[A-Za-z0-9]{6}"
    assert activation["autocapitalize"] == "characters"
    assert activation["autocorrect"] == "off"
    assert "activation-code-error" in activation["aria-describedby"]

    for error_id in ("student-no-error", "student-name-error", "activation-code-error"):
        assert parser.by_id[error_id]["aria-live"] == "polite"


def test_student_login_normalization_validation_and_major_badges_execute_in_node() -> None:
    student_js_path = ROOT / "web" / "student.js"
    check = subprocess.run(
        ["node", "--check", str(student_js_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert check.returncode == 0, check.stderr

    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8").split("const studentState =", 1)[0];
eval(source + `
  const normalized = normalizeStudentLoginPayload({
    student_no: " ２０２６１２３４５６７ ",
    name: "  张 三·Alice  ",
    activation_code: " ａ1ｂ2ｃ3 ",
  });
  const result = {
    normalized,
    valid: validateStudentLoginPayload(normalized),
    invalid: validateStudentLoginPayload({
      student_no: "12<script>", name: "张三🙂", activation_code: "12*456"
    }),
    invalidNumbers: [
      {student_no: "2026123456", name: "正常姓名", activation_code: "A1B2C3"},
      {student_no: "202612345678", name: "正常姓名", activation_code: "A1B2C3"},
    ].map((payload) => validateStudentLoginPayload(payload)),
    unsafeEnvelope: {
      studentNoControl: validateStudentLoginPayload({
        student_no: "bad\\nnumber", name: "正常姓名", activation_code: "A1B2C3"
      }),
      nameControl: validateStudentLoginPayload({
        student_no: "20261234567", name: "坏\\u0007姓名", activation_code: "A1B2C3"
      }),
      studentNoTooLong: validateStudentLoginPayload({
        student_no: "L".repeat(41), name: "正常姓名", activation_code: "A1B2C3"
      }),
      nameTooLong: validateStudentLoginPayload({
        student_no: "20261234567", name: "名".repeat(81), activation_code: "A1B2C3"
      }),
    },
    badges: [
      professionalBadge("建筑学（五年制）"),
      professionalBadge("城乡规划"),
      professionalBadge("风景园林"),
      professionalBadge("室内设计"),
      professionalBadge(""),
    ],
    supportedNames: ["陳·嘉敏", "Alice Smith", "AnaMaria", "王 小明"].map((name) =>
      Object.keys(validateStudentLoginPayload({student_no: "20261234567", name, activation_code: "A1B2C3"})).length
    ),
  };
  process.stdout.write(JSON.stringify(result));
`);
"""
    execution = subprocess.run(
        ["node", "-e", script, str(student_js_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert execution.returncode == 0, execution.stderr
    result = json.loads(execution.stdout)
    assert result["normalized"] == {
        "student_no": "20261234567",
        "name": "张 三·Alice",
        "activation_code": "A1B2C3",
    }
    assert result["valid"] == {}
    assert set(result["invalid"]) == {"student_no", "name", "activation_code"}
    assert all(set(item) == {"student_no"} for item in result["invalidNumbers"])
    assert set(result["unsafeEnvelope"]["studentNoControl"]) == {"student_no"}
    assert set(result["unsafeEnvelope"]["nameControl"]) == {"name"}
    assert set(result["unsafeEnvelope"]["studentNoTooLong"]) == {"student_no"}
    assert set(result["unsafeEnvelope"]["nameTooLong"]) == {"name"}
    assert result["badges"] == ["建筑学", "城乡规划", "风景园林", "室内设计", "专业"]
    assert result["supportedNames"] == [0, 0, 0, 0]


def test_major_badges_and_standardized_result_card_are_exposed_without_secrets() -> None:
    parser, html = _student_dom()
    student_js = (ROOT / "web" / "student.js").read_text(encoding="utf-8")

    assert "const STUDENT_NO_INPUT_LENGTH = 11" in student_js
    assert "const STUDENT_NAME_MAX_INPUT_LENGTH = 40" in student_js
    assert '.replace(/\\D/g, "").slice(0, STUDENT_NO_INPUT_LENGTH)' in student_js
    assert 'studentLoginFields.student_no.input.removeAttribute("pattern")' not in student_js
    assert 'studentLoginFields.name.input.removeAttribute("pattern")' not in student_js

    for badge_id in ("student-major-badge", "waiting-major-badge"):
        badge = parser.by_id[badge_id]
        assert badge["role"] == "img"
        assert badge["aria-label"] == "专业标识"
        assert parser.text_by_id[badge_id].strip() == "专"
    assert '<div class="student-avatar" aria-hidden="true">建</div>' not in html

    download = parser.by_id["download-result-card"]
    assert download["tag"] == "button"
    assert download["type"] == "button"
    assert "下载抢选结果凭证" in parser.text_by_id["download-result-card"]

    card_source = student_js.split("async function createResultCardBlob", 1)[1].split(
        "async function downloadStudentResultCard", 1
    )[0]
    assert "canvas.width = 1080" in card_source
    assert "canvas.height = 1350" in card_source
    assert '"/brand/college-wordmark-official.png"' in student_js
    assert "context.fillRect(48, 40, 984, 274)" in card_source
    assert card_source.index("context.fillRect(48, 40, 984, 274)") < card_source.index(
        "context.drawImage(logo"
    )
    assert "安徽建筑大学 · 建筑与空间规划学院  制作：Mikutea" in card_source
    assert "activation_code" not in card_source
    assert "个人激活码" not in card_source
    assert "结果卡生成失败" in student_js
    assert "学院标识加载失败" in student_js


def test_invalid_identity_fields_expose_accessible_error_state() -> None:
    student_js = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    error_block = student_js.split("function setStudentFieldError", 1)[1].split(
        "function clearStudentFieldErrors", 1
    )[0]

    assert 'setAttribute("aria-invalid", "true")' in error_block
    assert 'removeAttribute("aria-invalid")' in error_block
    assert 'toggleAttribute("aria-invalid"' not in error_block


def test_student_phase_transitions_have_actionable_non_repeating_messages() -> None:
    student_js = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    transition_source = student_js.split("function announceStudentPhaseTransition", 1)[1].split(
        "function renderStudentPayload", 1
    )[0]
    assert "previous === phase" in transition_source
    assert "统一倒计时已启动" in transition_source
    assert "抢选现已开放" in transition_source
    assert "抢选已暂停" in transition_source
    assert "本场抢选已关闭" in transition_source
    assert 'document.body.dataset.studentView = "success"' in student_js
    assert 'document.body.dataset.studentView = "choice"' in student_js
