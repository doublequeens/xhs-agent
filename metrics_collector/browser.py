import os
import stat
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from metrics_collector.config import CollectorConfig


_BODY_TEXT_LIMIT = 10_000
_CREATOR_HOST = "creator.xiaohongshu.com"
_NAVIGATION_TIMEOUT_MS = 30_000
_READINESS_MARKER = "创作服务平台"


class CollectorBrowserError(RuntimeError):
    pass


class AuthenticationRequired(CollectorBrowserError):
    pass


class VerificationRequired(CollectorBrowserError):
    pass


class AccessBlocked(CollectorBrowserError):
    pass


class BrowserNavigationError(CollectorBrowserError):
    pass


class BrowserSession:
    def __init__(
        self,
        config: CollectorConfig,
        playwright_factory: Callable[[], Any] = sync_playwright,
        repository_root: Path | None = None,
    ) -> None:
        self.config = config
        self._playwright_factory = playwright_factory
        self.repository_root = (
            repository_root.resolve()
            if repository_root is not None
            else Path(__file__).resolve().parents[1]
        )
        self._playwright: Any | None = None
        self.context: Any | None = None
        self.page: Any | None = None

    def start(self) -> None:
        if (
            self._playwright is not None
            or self.context is not None
            or self.page is not None
        ):
            raise CollectorBrowserError("browser session already started")

        private_directories = (
            self.config.profile_dir,
            self.config.download_dir,
        )
        for path in private_directories:
            _validate_private_directory(path, self.repository_root)
        for path in private_directories:
            _create_private_directory(path, self.repository_root)

        self._playwright = self._playwright_factory().start()
        try:
            self.context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.config.profile_dir),
                channel=self.config.browser_channel,
                headless=False,
                accept_downloads=True,
                downloads_path=str(self.config.download_dir),
            )
            self.page = (
                self.context.pages[0]
                if self.context.pages
                else self.context.new_page()
            )
        except Exception as startup_error:
            try:
                self.close()
            except Exception as cleanup_error:
                _add_cleanup_note(startup_error, cleanup_error)
            raise

    def navigate(self, url: str) -> Any:
        if self.page is None:
            raise CollectorBrowserError("browser session not started")

        try:
            response = self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=_NAVIGATION_TIMEOUT_MS,
            )
        except Exception as error:
            raise BrowserNavigationError("browser navigation failed") from error

        status = response.status if response is not None else None
        if status == 401:
            raise AuthenticationRequired("creator center authentication required")
        if status in {403, 429}:
            raise AccessBlocked("creator center access blocked")
        if status is not None and status >= 400:
            raise BrowserNavigationError(
                f"creator center navigation returned HTTP {status}"
            )

        requested_path = urlparse(url).path
        _wait_for_creator_body_marker(self.page)
        assert_creator_center_ready(self.page, expected_path=requested_path)
        return response

    def close(self) -> None:
        cleanup_errors: list[Exception] = []

        context = self.context
        if context is None:
            self.page = None
        else:
            try:
                context.close()
            except Exception as error:
                cleanup_errors.append(error)
            else:
                self.context = None
                self.page = None

        playwright = self._playwright
        if playwright is not None:
            try:
                playwright.stop()
            except Exception as error:
                cleanup_errors.append(error)
            else:
                self._playwright = None
                self.context = None
                self.page = None

        if cleanup_errors:
            primary_error = cleanup_errors[0]
            for secondary_error in cleanup_errors[1:]:
                primary_error.add_note(
                    f"Additional browser cleanup failure: {secondary_error}"
                )
            raise primary_error

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            self.close()
        except Exception as cleanup_error:
            if exc_value is None:
                raise
            _add_cleanup_note(exc_value, cleanup_error)
        return False


def assert_creator_center_ready(
    page: Any,
    expected_path: str | None = None,
) -> None:
    try:
        current_url = page.url
        parsed_url = urlparse(current_url)
    except Exception as error:
        raise BrowserNavigationError("creator page inspection failed") from error

    if (
        parsed_url.scheme.lower() != "https"
        or parsed_url.netloc.lower() != _CREATOR_HOST
    ):
        raise BrowserNavigationError("unexpected creator page origin")

    path_lower = parsed_url.path.lower()
    query = {
        key.lower(): values
        for key, values in parse_qs(parsed_url.query).items()
    }
    redirect_reasons = [
        value.lower()
        for value in query.get("redirectreason", [])
    ]
    is_login_url = path_lower == "/login" or path_lower.startswith("/login/")
    if is_login_url or "401" in redirect_reasons:
        raise AuthenticationRequired("creator center authentication required")

    path_segments = [segment for segment in path_lower.split("/") if segment]
    verification_path_prefixes = ("verify", "security", "captcha")
    if any(
        segment.startswith(verification_path_prefixes)
        for segment in path_segments
    ):
        raise VerificationRequired("creator center verification required")

    if (
        expected_path is not None
        and _normalize_url_path(parsed_url.path)
        != _normalize_url_path(expected_path)
    ):
        raise BrowserNavigationError("unexpected creator page path")

    try:
        page_text = page.locator("body").evaluate(
            """
            (body, limit) => {
                const selectors = [
                    '[role="alert"]',
                    '[class*="error" i]',
                    '[class*="toast" i]',
                    '[class*="message" i]',
                    '[class*="error-page" i]'
                ].join(',');
                const parts = [];
                let used = 0;
                for (const element of body.querySelectorAll(selectors)) {
                    const text = (element.innerText || '').trim();
                    const remaining = limit - used;
                    if (!text || remaining <= 0) {
                        continue;
                    }
                    const bounded = text.slice(0, remaining);
                    parts.push(bounded);
                    used += bounded.length + 1;
                }
                return {
                    bodyText: (body.innerText || '').slice(0, limit),
                    errorText: parts.join('\\n').slice(0, limit)
                };
            }
            """,
            _BODY_TEXT_LIMIT,
        )
    except Exception as error:
        raise BrowserNavigationError("creator page inspection failed") from error

    if not isinstance(page_text, dict):
        raise BrowserNavigationError("creator page inspection failed")
    body_text = page_text.get("bodyText")
    error_text = page_text.get("errorText")
    body_text = body_text if isinstance(body_text, str) else ""
    error_text = error_text if isinstance(error_text, str) else ""

    _raise_for_stop_text(error_text)
    has_readiness_marker = _READINESS_MARKER in body_text
    if not has_readiness_marker and len(body_text.strip()) <= 2_000:
        _raise_for_stop_text(body_text)
    if not has_readiness_marker:
        raise BrowserNavigationError("creator page not ready")


def _wait_for_creator_body_marker(page: Any) -> None:
    try:
        page.wait_for_function(
            """
                ([marker, limit]) => {
                    const text = (document.body?.innerText || '').slice(0, limit);
                    return text.includes(marker);
                }
                """,
            arg=[_READINESS_MARKER, _BODY_TEXT_LIMIT],
            timeout=_NAVIGATION_TIMEOUT_MS,
        )
    except Exception:
        pass


def _raise_for_stop_text(text: str) -> None:
    text_lower = text.lower()
    access_markers = (
        "操作频繁",
        "访问受限",
        "请求过于频繁",
        "forbidden",
    )
    if any(marker in text_lower for marker in access_markers):
        raise AccessBlocked("creator center access blocked")

    verification_markers = (
        "请完成安全验证",
        "安全验证",
        "请完成验证",
        "人机验证",
        "拖动滑块",
    )
    if any(marker in text for marker in verification_markers):
        raise VerificationRequired("creator center verification required")

    login_markers = ("短信登录", "扫码登录", "请登录")
    if any(marker in text for marker in login_markers):
        raise AuthenticationRequired("creator center authentication required")


def _validate_private_directory(path: Path, repository_root: Path) -> None:
    absolute_path = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute_path.anchor)
    for component in absolute_path.parts[1:]:
        if component == "..":
            current = current.parent
            continue
        if component == ".":
            continue
        current /= component
        try:
            component_stat = current.lstat()
        except FileNotFoundError:
            continue
        except NotADirectoryError as error:
            raise CollectorBrowserError(
                f"private directory path is not a directory: {path}"
            ) from error
        if stat.S_ISLNK(component_stat.st_mode):
            raise CollectorBrowserError(
                f"private directory path contains a symlink: {path}"
            )
        if not stat.S_ISDIR(component_stat.st_mode):
            raise CollectorBrowserError(
                f"private directory path is not a directory: {path}"
            )

    resolved_path = absolute_path.resolve(strict=False)
    try:
        resolved_path.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise CollectorBrowserError(
            f"private directory must be outside repository: {path}"
        )

    try:
        path_stat = absolute_path.stat()
    except FileNotFoundError:
        return
    except NotADirectoryError as error:
        raise CollectorBrowserError(
            f"private directory path is not a directory: {path}"
        ) from error
    if path_stat.st_uid != os.getuid():
        raise CollectorBrowserError(
            f"private directory is not owned by current user: {path}"
        )


def _create_private_directory(path: Path, repository_root: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    _validate_private_directory(path, repository_root)
    path.chmod(0o700)


def _add_cleanup_note(primary_error: BaseException, cleanup_error: Exception) -> None:
    details = str(cleanup_error)
    cleanup_notes = getattr(cleanup_error, "__notes__", ())
    if cleanup_notes:
        details = f"{details}; {'; '.join(cleanup_notes)}"
    primary_error.add_note(f"Browser cleanup failed: {details}")


def _normalize_url_path(path: str) -> str:
    return path.rstrip("/") or "/"
