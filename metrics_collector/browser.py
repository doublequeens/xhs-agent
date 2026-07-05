from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from metrics_collector.config import CollectorConfig


_BODY_TEXT_LIMIT = 10_000
_NAVIGATION_TIMEOUT_MS = 30_000


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
    ) -> None:
        self.config = config
        self._playwright_factory = playwright_factory
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

        _create_private_directory(self.config.profile_dir)
        _create_private_directory(self.config.download_dir)

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
        except Exception:
            try:
                self.close()
            except Exception:
                pass
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

        assert_creator_center_ready(self.page)
        return response

    def close(self) -> None:
        context, self.context = self.context, None
        playwright, self._playwright = self._playwright, None
        self.page = None

        close_error: Exception | None = None
        try:
            if context is not None:
                context.close()
        except Exception as error:
            close_error = error
        finally:
            try:
                if playwright is not None:
                    playwright.stop()
            except Exception as error:
                if close_error is None:
                    close_error = error

        if close_error is not None:
            raise close_error

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def assert_creator_center_ready(page: Any) -> None:
    try:
        current_url = page.url
        body_text = page.locator("body").evaluate(
            "(body, limit) => body.innerText.slice(0, limit)",
            _BODY_TEXT_LIMIT,
        )
    except Exception as error:
        raise BrowserNavigationError("creator page inspection failed") from error

    text = body_text if isinstance(body_text, str) else ""
    text_lower = text.lower()
    url_lower = current_url.lower()

    access_markers = (
        "操作频繁",
        "访问受限",
        "请求过于频繁",
        "forbidden",
    )
    if any(
        marker in text_lower or marker in url_lower
        for marker in access_markers
    ):
        raise AccessBlocked("creator center access blocked")

    parsed_url = urlparse(current_url)
    path_lower = parsed_url.path.lower()
    is_verification_url = path_lower == "/verify" or path_lower.startswith(
        "/verify/"
    )
    verification_text = (
        "安全验证" in text
        or "请完成验证" in text
        or _contains_verification_code_challenge(text)
    )
    if is_verification_url or verification_text:
        raise VerificationRequired("creator center verification required")

    query = {key.lower(): values for key, values in parse_qs(parsed_url.query).items()}
    redirect_reasons = [value.lower() for value in query.get("redirectreason", [])]
    is_login_url = path_lower == "/login" or path_lower.startswith("/login/")
    login_markers = ("短信登录", "扫码登录", "请登录", "登录后")
    if (
        is_login_url
        or "401" in redirect_reasons
        or any(marker in text for marker in login_markers)
    ):
        raise AuthenticationRequired("creator center authentication required")


def _contains_verification_code_challenge(text: str) -> bool:
    if text.strip() == "验证码":
        return True
    challenge_markers = (
        "请输入验证码",
        "获取验证码",
        "发送验证码",
        "验证码以继续",
        "完成验证码",
    )
    return any(marker in text for marker in challenge_markers)


def _create_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)
