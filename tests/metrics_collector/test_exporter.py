from pathlib import Path

import pytest

from metrics_collector.browser import AuthenticationRequired
from metrics_collector.exporter import ExportError, MetricsExporter


HEALTHY_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
HEALTHY_BODY = "小红书创作服务平台 数据分析"
VALID_XLSX_BYTES = b"PK\x03\x04official workbook content"


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

    def count(self):
        return self.page.download_button_count

    def click(self):
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
    ):
        self.url = url
        self.download = download if download is not None else FakeDownload()
        self.download_button_count = download_button_count
        self.body_text = body_text
        self.timeout_on_value = timeout_on_value
        self.readiness_error = readiness_error
        self.export_clicks = 0
        self.expect_download_calls = 0
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


def test_export_clicks_once_and_saves_completed_xlsx(tmp_path):
    fake_page = FakePage()
    exporter = MetricsExporter(download_dir=tmp_path)

    path = exporter.export(fake_page)

    assert fake_page.export_clicks == 1
    assert fake_page.expect_download_calls == 1
    assert path.suffix == ".xlsx"
    assert path.exists()
    assert path.read_bytes() == VALID_XLSX_BYTES


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


def test_export_uses_unique_paths_for_repeated_suggested_filename(tmp_path):
    exporter = MetricsExporter(download_dir=tmp_path)

    first_path = exporter.export(FakePage())
    second_path = exporter.export(FakePage())

    assert first_path != second_path
    assert first_path.parent == tmp_path
    assert second_path.parent == tmp_path
