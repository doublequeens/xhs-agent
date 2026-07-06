from pathlib import Path

import pytest

from metrics_collector.browser import AuthenticationRequired
from metrics_collector.exporter import ExportError, MetricsExporter


HEALTHY_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
HEALTHY_BODY = "小红书创作服务平台 数据分析"
VALID_XLSX_BYTES = b"PK\x03\x04official workbook content"
BUTTON_ENABLED_WAIT = (
    "(selector) => {\n"
    "    const buttons = Array.from(document.querySelectorAll(selector));\n"
    "    if (buttons.length !== 1) return false;\n"
    "    const button = buttons[0];\n"
    "    return !button.disabled && "
    "button.getAttribute('aria-disabled') !== 'true' && "
    "!button.classList.contains('disabled');\n"
    "}"
)


class FakeBodyLocator:
    def __init__(self, page):
        self.page = page

    def evaluate(self, expression, limit):
        if self.page.readiness_error is not None:
            raise self.page.readiness_error
        return {"bodyText": self.page.body_text[:limit], "errorText": ""}


class FakeButtonLocator:
    def __init__(self, page):
        self.page = page

    def wait_for(self, **options):
        self.page.wait_for_calls.append(options)
        self.page.download_button_count = self.page.ready_download_button_count

    def count(self):
        return self.page.download_button_count

    def evaluate(self, expression):
        self.page.enabled_evaluate_calls.append(expression)
        return self.page.download_button_enabled

    def click(self, **options):
        if options.get("trial"):
            raise AssertionError("trial click is not allowed")
        if not self.page.download_button_enabled:
            raise AssertionError("disabled button was clicked")
        self.page.export_clicks += 1


class FakeDownload:
    def __init__(self, suggested_filename="metrics.xlsx", content=VALID_XLSX_BYTES):
        self.suggested_filename = suggested_filename
        self.content = content
        self.save_paths = []

    def save_as(self, path):
        self.save_paths.append(Path(path))
        Path(path).write_bytes(self.content)


class FakeDownloadInfo:
    def __init__(self, page):
        self.page = page

    @property
    def value(self):
        if self.page.timeout_on_value:
            raise TimeoutError("download timed out")
        return self.page.download


class FakeExpectDownload:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return FakeDownloadInfo(self.page)

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakePage:
    def __init__(
        self,
        *,
        download=None,
        download_button_count=1,
        body_text=HEALTHY_BODY,
        timeout_on_value=False,
        readiness_error=None,
        url=HEALTHY_URL,
        ready_download_button_count=None,
        download_button_enabled=True,
        ready_download_button_enabled=None,
    ):
        self.url = url
        self.download = download if download is not None else FakeDownload()
        self.download_button_count = download_button_count
        self.ready_download_button_count = (
            ready_download_button_count
            if ready_download_button_count is not None
            else download_button_count
        )
        self.download_button_enabled = download_button_enabled
        self.ready_download_button_enabled = (
            ready_download_button_enabled
            if ready_download_button_enabled is not None
            else download_button_enabled
        )
        self.body_text = body_text
        self.timeout_on_value = timeout_on_value
        self.readiness_error = readiness_error
        self.export_clicks = 0
        self.expect_download_calls = 0
        self.wait_for_calls = []
        self.wait_for_function_calls = []
        self.enabled_evaluate_calls = []
        self.locator_calls = []

    def locator(self, selector):
        self.locator_calls.append(selector)
        if selector == "body":
            return FakeBodyLocator(self)
        if selector == "button.download-btn":
            return FakeButtonLocator(self)
        raise AssertionError(f"unexpected selector: {selector}")

    def expect_download(self):
        self.expect_download_calls += 1
        return FakeExpectDownload(self)

    def wait_for_function(self, expression, arg=None):
        self.wait_for_function_calls.append((expression, arg))
        self.download_button_enabled = self.ready_download_button_enabled
        if not self.download_button_enabled:
            raise TimeoutError("button enabled timed out")


def test_export_clicks_once_and_saves_completed_xlsx(tmp_path):
    fake_page = FakePage()
    exporter = MetricsExporter(download_dir=tmp_path)

    path = exporter.export(fake_page)

    assert fake_page.export_clicks == 1
    assert fake_page.enabled_evaluate_calls == []
    assert fake_page.wait_for_function_calls == [
        (BUTTON_ENABLED_WAIT, "button.download-btn")
    ]
    assert fake_page.expect_download_calls == 1
    assert path.suffix == ".xlsx"
    assert path.exists()
    assert path.read_bytes() == VALID_XLSX_BYTES


def test_export_waits_for_delayed_visible_download_button(tmp_path):
    fake_page = FakePage(
        download_button_count=0,
        ready_download_button_count=1,
        download_button_enabled=True,
    )
    exporter = MetricsExporter(download_dir=tmp_path)

    path = exporter.export(fake_page)

    assert path.exists()
    assert fake_page.wait_for_calls == [{"state": "visible"}]
    assert fake_page.enabled_evaluate_calls == []
    assert len(fake_page.wait_for_function_calls) == 1
    assert fake_page.export_clicks == 1
    assert fake_page.expect_download_calls == 1


def test_export_waits_for_visible_button_to_become_enabled(tmp_path):
    fake_page = FakePage(
        download_button_enabled=False,
        ready_download_button_enabled=True,
    )
    exporter = MetricsExporter(download_dir=tmp_path)

    path = exporter.export(fake_page)

    assert path.exists()
    assert fake_page.wait_for_calls == [{"state": "visible"}]
    assert fake_page.enabled_evaluate_calls == []
    assert fake_page.wait_for_function_calls == [
        (BUTTON_ENABLED_WAIT, "button.download-btn")
    ]
    assert fake_page.export_clicks == 1
    assert fake_page.expect_download_calls == 1


def test_export_rejects_disabled_download_button_without_clicking(tmp_path):
    fake_page = FakePage(download_button_enabled=False)
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="enabled"):
        exporter.export(fake_page)

    assert fake_page.wait_for_calls == [{"state": "visible"}]
    assert fake_page.enabled_evaluate_calls == []
    assert len(fake_page.wait_for_function_calls) == 1
    assert fake_page.export_clicks == 0
    assert fake_page.expect_download_calls == 0


def test_export_rejects_non_xlsx_download(tmp_path):
    fake_page = FakePage(download=FakeDownload(suggested_filename="error.html"))
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match=r"expected \.xlsx"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 1
    assert fake_page.expect_download_calls == 1


def test_export_timeout_does_not_retry(tmp_path):
    fake_page = FakePage(timeout_on_value=True)
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="timed out"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 1
    assert fake_page.expect_download_calls == 1


@pytest.mark.parametrize("button_count", [0, 2])
def test_export_requires_exactly_one_download_button_without_clicking(
    tmp_path,
    button_count,
):
    fake_page = FakePage(download_button_count=button_count)
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="exactly one"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 0
    assert fake_page.expect_download_calls == 0


def test_export_rejects_empty_download(tmp_path):
    fake_page = FakePage(download=FakeDownload(content=b""))
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="empty"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 1


def test_export_rejects_invalid_zip_signature(tmp_path):
    fake_page = FakePage(download=FakeDownload(content=b"<html></html>"))
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="ZIP signature"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 1


def test_export_rejects_crdownload_filename(tmp_path):
    fake_page = FakePage(
        download=FakeDownload(suggested_filename="metrics.xlsx.crdownload")
    )
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="crdownload"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 1


def test_export_propagates_readiness_failures_without_clicking(tmp_path):
    fake_page = FakePage(url="https://creator.xiaohongshu.com/login")
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(AuthenticationRequired):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 0
    assert fake_page.expect_download_calls == 0


def test_export_does_not_retry_after_save_failure(tmp_path):
    class FailingDownload(FakeDownload):
        def save_as(self, path):
            self.save_paths.append(Path(path))
            raise OSError("disk full")

    fake_page = FakePage(download=FailingDownload())
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="save"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 1
    assert fake_page.expect_download_calls == 1


def test_export_removes_partial_file_after_save_failure(tmp_path):
    class PartiallyFailingDownload(FakeDownload):
        def save_as(self, path):
            self.save_paths.append(Path(path))
            Path(path).write_bytes(VALID_XLSX_BYTES)
            raise OSError("connection reset")

    download = PartiallyFailingDownload()
    fake_page = FakePage(download=download)
    exporter = MetricsExporter(download_dir=tmp_path)

    with pytest.raises(ExportError, match="save"):
        exporter.export(fake_page)

    assert fake_page.export_clicks == 1
    assert fake_page.expect_download_calls == 1
    assert len(download.save_paths) == 1
    assert not download.save_paths[0].exists()


def test_export_uses_unique_paths_for_repeated_suggested_filename(tmp_path):
    exporter = MetricsExporter(download_dir=tmp_path)

    first_path = exporter.export(FakePage())
    second_path = exporter.export(FakePage())

    assert first_path != second_path
    assert first_path.parent == tmp_path
    assert second_path.parent == tmp_path
