from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            self.ids[element_id] = {"tag": tag, **values}


def _sources() -> tuple[str, str, str]:
    return (
        (ROOT / "web" / "admin.html").read_text(encoding="utf-8"),
        (ROOT / "web" / "admin.js").read_text(encoding="utf-8"),
        (ROOT / "web" / "app.css").read_text(encoding="utf-8"),
    )


def test_projection_has_phase_specific_regions_and_full_screen_countdown():
    html, javascript, css = _sources()
    parser = _Ids()
    parser.feed(html)

    assert parser.ids["waiting-overview"]["tag"] == "div"
    assert parser.ids["live-selection-feed"]["tag"] == "div"
    assert parser.ids["unselected-list"]["tag"] == "div"
    assert parser.ids["board-countdown-overlay"]["tag"] == "section"
    assert parser.ids["board-overlay-countdown"]["tag"] == "strong"
    assert 'liveBoard.classList.toggle("phase-waiting"' in javascript
    assert 'liveBoard.classList.toggle("phase-selection"' in javascript
    assert 'liveBoard.classList.toggle("phase-countdown"' in javascript
    assert ".live-board.phase-waiting .selection-only" in css
    assert ".live-board.phase-selection .waiting-overview" in css
    assert ".live-board:fullscreen.phase-countdown .board-countdown-overlay" in css
    assert "countdown-number" in css
    assert "college-wordmark--countdown" in html
    assert "countdown-architecture" not in html
    assert "countdown-orbit" not in html


def test_projection_rosters_are_continuous_only_when_they_overflow():
    _, javascript, css = _sources()

    assert "list.scrollHeight > list.clientHeight + 4" in javascript
    assert 'clone.dataset.rosterClone = "true"' in javascript
    assert 'clone.dataset.feedClone = "true"' in javascript
    assert "captureRosterScrollRatio" in javascript
    assert "captureLiveFeedScrollRatio" in javascript
    assert "setupRosterLoop(previousScrollRatio)" in javascript
    assert "setupLiveFeedLoop(previousScrollRatio)" in javascript
    assert "reducedMotionPreference.matches" in javascript
    assert ".live-selection-feed" in css and "overflow: hidden" in css
    assert ".unselected-list::-webkit-scrollbar" in css


def test_review_p2_fingerprints_are_complete_and_restart_after_session_change():
    _, javascript, _ = _sources()

    live_feed_block = javascript.split("function renderLiveSelectionFeed", 1)[1].split(
        "function renderQr", 1
    )[0]
    assert "record.major_name" in live_feed_block
    login_block = javascript.split("function showAdminLogin", 1)[1].split(
        "function dashboardField", 1
    )[0]
    assert 'adminState.rosterFingerprint = ""' in login_block
    assert 'adminState.liveFeedFingerprint = ""' in login_block
    assert "stopRosterAutoScroll()" in login_block
    assert "stopLiveFeedAutoScroll()" in login_block


def test_absent_students_require_an_explicit_but_overridable_warning():
    _, javascript, _ = _sources()
    action_block = javascript.split("async function handleSelectionPhaseAction", 1)[1].split(
        "adminEls.statusButton.addEventListener", 1
    )[0]

    assert "presence.absent > 0" in action_block
    assert "未进入候场" in action_block
    assert "仍可继续开始" in action_block
    assert "absentStudents.map" in action_block
    assert 'await adminApi("/api/admin/countdown"' in action_block


def test_admin_uses_single_activity_name_source_and_excel_result_export():
    html, javascript, _ = _sources()
    parser = _Ids()
    parser.feed(html)

    settings_block = html.split('<form id="settings-form"', 1)[1].split("</form>", 1)[0]
    assert 'name="activity_title"' not in settings_block
    assert "访问与版权" in settings_block
    assert 'name="title"' in html
    assert parser.ids["export-complete-results"]["href"] == "/api/admin/export/results.xlsx"
    assert "/api/admin/export/results.xlsx?" in javascript
    assert "全员已完成，可导出统一 Excel" in html
    assert 'Number(data.totals.unselected) === 0' in javascript


def test_archive_delete_is_double_confirmed_and_current_activity_is_cas_guarded():
    _, javascript, _ = _sources()
    block = javascript.split('remove.dataset.action = "delete-archive"', 1)[1].split(
        "function renderGroupProgress", 1
    )[0]

    assert block.count("await confirmDanger") == 2
    assert 'method: "DELETE"' in block
    assert 'confirmation: "DELETE"' in block
    assert "activityId: adminState.dashboard?.settings.activity_id" in block
    assert "不可撤销" in block


def test_roster_has_reveal_only_contract_and_template_has_no_public_accounts():
    html, javascript, _ = _sources()

    assert "显示明文" in javascript
    assert "••••••" in javascript
    assert "••••••••" not in javascript
    assert "reset-activation-code" not in javascript
    assert "重置激活码" not in html
    template_block = javascript.split('document.querySelector("#download-template")', 1)[1].split(
        "for (const [anchor", 1
    )[0]
    assert '[[' + '"学号", "姓名", "专业名称", "证件号"' + "]" in template_block
    assert "示例学生" not in template_block


def test_board_logo_crop_matches_official_asset_transparency_bounds():
    _, _, css = _sources()
    logo_block = css.split(".college-wordmark--board {", 1)[1].split(
        ".board-presentation-brand h1", 1
    )[0]

    assert "width: clamp(310px,22vw,390px)" in logo_block
    assert "height: clamp(76px,5.3vw,92px)" in logo_block
    assert "width: 106.8%" in logo_block
    assert "left: -7%" in logo_block
    assert "top: -16.5%" in logo_block
