from pathlib import Path
from uuid import uuid4

from metrics_collector.browser import assert_creator_center_ready


_DOWNLOAD_BUTTON_SELECTOR = "button.download-btn"
_BUTTON_ENABLED_WAIT = (
    "(selector) => {\n"
    "    const buttons = Array.from(document.querySelectorAll(selector));\n"
    "    if (buttons.length !== 1) return false;\n"
    "    const button = buttons[0];\n"
    "    return !button.disabled && "
    "button.getAttribute('aria-disabled') !== 'true' && "
    "!button.classList.contains('disabled');\n"
    "}"
)


class ExportError(RuntimeError):
    pass


class MetricsExporter:
    def __init__(self, download_dir: Path | str) -> None:
        self.download_dir = Path(download_dir)

    def export(self, page) -> Path:
        assert_creator_center_ready(page)

        download_button = page.locator(_DOWNLOAD_BUTTON_SELECTOR)
        _wait_for_unique_download_button(page, download_button)

        try:
            with page.expect_download() as download_info:
                download_button.click()
            download = download_info.value
        except Exception as exc:
            if _looks_like_timeout(exc):
                raise ExportError("export timed out") from exc
            raise ExportError("export download failed") from exc

        suggested_filename = str(download.suggested_filename)
        _validate_suggested_filename(suggested_filename)
        destination = self._unique_destination(suggested_filename)

        try:
            download.save_as(destination)
        except Exception as exc:
            _remove_if_present(destination)
            raise ExportError("failed to save export download") from exc

        try:
            _validate_saved_workbook(destination)
        except ExportError:
            _remove_if_present(destination)
            raise

        return destination

    def _unique_destination(self, suggested_filename: str) -> Path:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        suggested_path = Path(suggested_filename)
        stem = suggested_path.stem or "metrics"
        for _ in range(100):
            candidate = self.download_dir / f"{stem}-{uuid4().hex}.xlsx"
            if not candidate.exists():
                return candidate
        raise ExportError("could not allocate unique export path")


def _wait_for_unique_download_button(page, download_button) -> None:
    try:
        download_button.wait_for(state="visible")
        button_count = download_button.count()
    except Exception as exc:
        if _looks_like_timeout(exc):
            raise ExportError("download button timed out") from exc
        raise ExportError("download button not ready") from exc

    if button_count != 1:
        raise ExportError(
            "expected exactly one button.download-btn, "
            f"found {button_count}"
        )

    try:
        page.wait_for_function(_BUTTON_ENABLED_WAIT, _DOWNLOAD_BUTTON_SELECTOR)
    except Exception as exc:
        if _looks_like_timeout(exc):
            raise ExportError("download button did not become enabled") from exc
        raise ExportError("download button enabled check failed") from exc


def _validate_suggested_filename(suggested_filename: str) -> None:
    suffixes = [suffix.lower() for suffix in Path(suggested_filename).suffixes]
    if suffixes and suffixes[-1] == ".crdownload":
        raise ExportError("download is incomplete: .crdownload file")
    if Path(suggested_filename).suffix.lower() != ".xlsx":
        raise ExportError("expected .xlsx download")


def _validate_saved_workbook(path: Path) -> None:
    if path.suffix.lower() == ".crdownload":
        raise ExportError("download is incomplete: .crdownload file")
    try:
        with path.open("rb") as handle:
            signature = handle.read(4)
    except OSError as exc:
        raise ExportError("could not read saved export download") from exc
    if not signature:
        raise ExportError("export download is empty")
    if signature != b"PK\x03\x04":
        raise ExportError("export download has invalid ZIP signature")


def _remove_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _looks_like_timeout(exc: Exception) -> bool:
    details = f"{type(exc).__name__}: {exc}".lower()
    return "timeout" in details or "timed out" in details
