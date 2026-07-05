import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from metrics_collector.browser import (
    AccessBlocked,
    AuthenticationRequired,
    BrowserNavigationError,
    BrowserSession,
    CollectorBrowserError,
    VerificationRequired,
    assert_creator_center_ready,
)
from metrics_collector.config import CollectorConfig


HEALTHY_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
HEALTHY_BODY = "小红书创作服务平台 数据分析"


class FakeResponse:
    def __init__(self, status):
        self.status = status


class FakeBodyLocator:
    def __init__(self, page):
        self.page = page

    def evaluate(self, expression, limit):
        self.page.evaluate_calls.append((expression, limit))
        if self.page.body_error is not None:
            raise self.page.body_error
        return self.page.body_text[:limit]


class FakePage:
    def __init__(
        self,
        *,
        url=HEALTHY_URL,
        body_text=HEALTHY_BODY,
        response=None,
        goto_error=None,
        body_error=None,
        final_url=None,
    ):
        self.url = url
        self.body_text = body_text
        self.response = response if response is not None else FakeResponse(200)
        self.goto_error = goto_error
        self.body_error = body_error
        self.final_url = final_url
        self.goto_calls = []
        self.locator_calls = []
        self.evaluate_calls = []

    def goto(self, url, **options):
        self.goto_calls.append((url, options))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url or url
        return self.response

    def locator(self, selector):
        self.locator_calls.append(selector)
        return FakeBodyLocator(self)


class FakeContext:
    def __init__(self, pages=None, close_error=None):
        self.pages = list(pages or [])
        self.close_error = close_error
        self.close_calls = 0
        self.new_page_calls = 0
        self.created_page = FakePage()

    def new_page(self):
        self.new_page_calls += 1
        return self.created_page

    def close(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeChromium:
    def __init__(self, context, launch_error=None):
        self.context = context
        self.launch_error = launch_error
        self.launch_calls = []

    def launch_persistent_context(self, **options):
        self.launch_calls.append(options)
        if self.launch_error is not None:
            raise self.launch_error
        return self.context


class FakePlaywright:
    def __init__(self, context, stop_error=None):
        self.chromium = FakeChromium(context)
        self.stop_error = stop_error
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        if self.stop_error is not None:
            raise self.stop_error


class FakePlaywrightStarter:
    def __init__(self, playwright):
        self.playwright = playwright
        self.start_calls = 0

    def start(self):
        self.start_calls += 1
        return self.playwright


class FakePlaywrightFactory:
    def __init__(self, playwright):
        self.starter = FakePlaywrightStarter(playwright)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.starter


@pytest.fixture
def browser_fakes():
    page = FakePage()
    context = FakeContext([page])
    playwright = FakePlaywright(context)
    factory = FakePlaywrightFactory(playwright)
    return page, context, playwright, factory


def _config(tmp_path):
    return CollectorConfig.default(home=tmp_path)


def test_start_launches_exact_persistent_headed_context_and_secures_dirs(
    tmp_path, browser_fakes
):
    _, _, playwright, factory = browser_fakes
    config = replace(_config(tmp_path), headless=True)
    config.profile_dir.mkdir(parents=True, mode=0o755)
    config.download_dir.mkdir(parents=True, mode=0o755)
    config.profile_dir.chmod(0o755)
    config.download_dir.chmod(0o755)

    session = BrowserSession(config, playwright_factory=factory)
    session.start()

    assert factory.calls == 1
    assert factory.starter.start_calls == 1
    assert playwright.chromium.launch_calls == [
        {
            "user_data_dir": str(config.profile_dir),
            "channel": config.browser_channel,
            "headless": False,
            "accept_downloads": True,
            "downloads_path": str(config.download_dir),
        }
    ]
    assert stat.S_IMODE(config.profile_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.download_dir.stat().st_mode) == 0o700


def test_start_uses_first_existing_page(tmp_path, browser_fakes):
    page, context, _, factory = browser_fakes

    session = BrowserSession(_config(tmp_path), playwright_factory=factory)
    session.start()

    assert session.page is page
    assert context.new_page_calls == 0


def test_start_creates_page_when_context_has_none(tmp_path):
    context = FakeContext()
    playwright = FakePlaywright(context)
    session = BrowserSession(
        _config(tmp_path), playwright_factory=FakePlaywrightFactory(playwright)
    )

    session.start()

    assert session.page is context.created_page
    assert context.new_page_calls == 1


def test_start_rejects_double_start(tmp_path, browser_fakes):
    _, _, playwright, factory = browser_fakes
    session = BrowserSession(_config(tmp_path), playwright_factory=factory)
    session.start()

    with pytest.raises(CollectorBrowserError, match="already started"):
        session.start()

    assert factory.calls == 1
    assert len(playwright.chromium.launch_calls) == 1


def test_start_stops_runtime_after_persistent_context_launch_fails(tmp_path):
    playwright = FakePlaywright(FakeContext())
    playwright.chromium = FakeChromium(
        FakeContext(), launch_error=RuntimeError("launch failed")
    )
    session = BrowserSession(
        _config(tmp_path), playwright_factory=FakePlaywrightFactory(playwright)
    )

    with pytest.raises(RuntimeError, match="launch failed"):
        session.start()

    assert playwright.stop_calls == 1
    session.close()
    assert playwright.stop_calls == 1


def test_start_preserves_startup_error_when_runtime_cleanup_fails(tmp_path):
    playwright = FakePlaywright(
        FakeContext(),
        stop_error=RuntimeError("runtime cleanup failed"),
    )
    playwright.chromium = FakeChromium(
        FakeContext(),
        launch_error=RuntimeError("launch failed"),
    )
    session = BrowserSession(
        _config(tmp_path),
        playwright_factory=FakePlaywrightFactory(playwright),
    )

    with pytest.raises(RuntimeError, match="launch failed") as exc_info:
        session.start()

    assert "runtime cleanup failed" in "\n".join(exc_info.value.__notes__)
    assert session._playwright is playwright
    playwright.stop_error = None
    session.close()
    assert playwright.stop_calls == 2


def test_context_manager_starts_and_closes_session(tmp_path, browser_fakes):
    page, context, playwright, factory = browser_fakes

    with BrowserSession(_config(tmp_path), playwright_factory=factory) as session:
        assert session.page is page

    assert context.close_calls == 1
    assert playwright.stop_calls == 1


def test_context_manager_closes_when_managed_body_raises(tmp_path, browser_fakes):
    _, context, playwright, factory = browser_fakes

    with pytest.raises(ValueError, match="collection failed"):
        with BrowserSession(_config(tmp_path), playwright_factory=factory):
            raise ValueError("collection failed")

    assert context.close_calls == 1
    assert playwright.stop_calls == 1


def test_context_manager_preserves_body_error_when_cleanup_fails(tmp_path):
    context = FakeContext(
        [FakePage()],
        close_error=RuntimeError("context cleanup failed"),
    )
    playwright = FakePlaywright(context)
    session = BrowserSession(
        _config(tmp_path),
        playwright_factory=FakePlaywrightFactory(playwright),
    )

    with pytest.raises(ValueError, match="collection failed") as exc_info:
        with session:
            raise ValueError("collection failed")

    assert "context cleanup failed" in "\n".join(exc_info.value.__notes__)
    assert session.context is context
    assert session._playwright is None
    context.close_error = None
    session.close()
    assert context.close_calls == 2


def test_close_stops_runtime_even_when_context_close_fails(tmp_path):
    context = FakeContext([FakePage()], close_error=RuntimeError("context close failed"))
    playwright = FakePlaywright(context)
    session = BrowserSession(
        _config(tmp_path), playwright_factory=FakePlaywrightFactory(playwright)
    )
    session.start()

    with pytest.raises(RuntimeError, match="context close failed"):
        session.close()

    assert context.close_calls == 1
    assert playwright.stop_calls == 1
    assert session.context is context
    assert session.page is not None
    assert session._playwright is None
    context.close_error = None
    session.close()
    assert context.close_calls == 2
    assert playwright.stop_calls == 1
    assert session.context is None
    assert session.page is None


def test_close_is_idempotent_when_runtime_stop_fails(tmp_path):
    context = FakeContext([FakePage()])
    playwright = FakePlaywright(context, stop_error=RuntimeError("stop failed"))
    session = BrowserSession(
        _config(tmp_path), playwright_factory=FakePlaywrightFactory(playwright)
    )
    session.start()

    with pytest.raises(RuntimeError, match="stop failed"):
        session.close()

    assert session.context is None
    assert session.page is None
    assert session._playwright is playwright
    playwright.stop_error = None
    session.close()
    assert context.close_calls == 1
    assert playwright.stop_calls == 2
    assert session._playwright is None


def test_close_attempts_and_retains_both_failed_handles(tmp_path):
    context = FakeContext(
        [FakePage()],
        close_error=RuntimeError("context close failed"),
    )
    playwright = FakePlaywright(
        context,
        stop_error=RuntimeError("runtime stop failed"),
    )
    session = BrowserSession(
        _config(tmp_path),
        playwright_factory=FakePlaywrightFactory(playwright),
    )
    session.start()

    with pytest.raises(RuntimeError, match="context close failed") as exc_info:
        session.close()

    assert "runtime stop failed" in "\n".join(exc_info.value.__notes__)
    assert context.close_calls == 1
    assert playwright.stop_calls == 1
    assert session.context is context
    assert session._playwright is playwright


def test_navigate_requires_started_session(tmp_path):
    session = BrowserSession(_config(tmp_path), playwright_factory=lambda: None)

    with pytest.raises(CollectorBrowserError, match="not started"):
        session.navigate(HEALTHY_URL)


def test_navigate_uses_bounded_domcontentloaded_goto(tmp_path, browser_fakes):
    page, _, _, factory = browser_fakes
    session = BrowserSession(_config(tmp_path), playwright_factory=factory)
    session.start()

    response = session.navigate(HEALTHY_URL)

    assert response is page.response
    assert page.goto_calls == [
        (
            HEALTHY_URL,
            {"wait_until": "domcontentloaded", "timeout": 30_000},
        )
    ]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AuthenticationRequired),
        (403, AccessBlocked),
        (429, AccessBlocked),
        (400, BrowserNavigationError),
        (404, BrowserNavigationError),
        (500, BrowserNavigationError),
    ],
)
def test_navigate_classifies_http_errors(tmp_path, status, error):
    page = FakePage(response=FakeResponse(status))
    context = FakeContext([page])
    session = BrowserSession(
        _config(tmp_path),
        playwright_factory=FakePlaywrightFactory(FakePlaywright(context)),
    )
    session.start()

    with pytest.raises(error):
        session.navigate(HEALTHY_URL)

    assert len(page.goto_calls) == 1
    assert page.locator_calls == []


def test_navigate_accepts_no_response_for_client_side_navigation(tmp_path):
    page = FakePage()
    page.response = None
    context = FakeContext([page])
    session = BrowserSession(
        _config(tmp_path),
        playwright_factory=FakePlaywrightFactory(FakePlaywright(context)),
    )
    session.start()

    assert session.navigate(HEALTHY_URL) is None


def test_navigate_wraps_goto_error_without_retry(tmp_path):
    page = FakePage(goto_error=TimeoutError("goto timed out"))
    context = FakeContext([page])
    session = BrowserSession(
        _config(tmp_path),
        playwright_factory=FakePlaywrightFactory(FakePlaywright(context)),
    )
    session.start()

    with pytest.raises(BrowserNavigationError, match="navigation failed") as exc_info:
        session.navigate(HEALTHY_URL)

    assert isinstance(exc_info.value.__cause__, TimeoutError)
    assert len(page.goto_calls) == 1


@pytest.mark.parametrize(
    "final_url",
    [
        "http://creator.xiaohongshu.com/statistics/data-analysis",
        "https://www.xiaohongshu.com/explore/example",
        "https://creator.xiaohongshu.com.evil.example/login",
        "https://sso.example.com/login",
    ],
)
def test_navigate_rejects_untrusted_final_origin(tmp_path, final_url):
    page = FakePage(final_url=final_url)
    context = FakeContext([page])
    session = BrowserSession(
        _config(tmp_path),
        playwright_factory=FakePlaywrightFactory(FakePlaywright(context)),
    )
    session.start()

    with pytest.raises(BrowserNavigationError, match="unexpected creator page origin"):
        session.navigate(HEALTHY_URL)


@pytest.mark.parametrize("body", ["", "创作中心 数据分析"])
def test_ready_page_requires_positive_platform_evidence(body):
    with pytest.raises(BrowserNavigationError, match="creator page not ready"):
        assert_creator_center_ready(FakePage(body_text=body))


def test_healthy_creator_page_passes_using_local_fixture():
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "metrics_collector"
        / "data_analysis.html"
    )
    page = FakePage(body_text=fixture.read_text(encoding="utf-8"))

    assert_creator_center_ready(page)


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("https://creator.xiaohongshu.com/login", "短信登录"),
        (f"{HEALTHY_URL}?redirectReason=401", HEALTHY_BODY),
        (HEALTHY_URL, "请登录后继续"),
        (HEALTHY_URL, "扫码登录"),
    ],
)
def test_login_states_require_authentication(url, body):
    with pytest.raises(AuthenticationRequired):
        assert_creator_center_ready(FakePage(url=url, body_text=body))


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("https://creator.xiaohongshu.com/verify", HEALTHY_BODY),
        ("https://creator.xiaohongshu.com/security/captcha", HEALTHY_BODY),
        (HEALTHY_URL, "请完成安全验证"),
        (HEALTHY_URL, "请进行人机验证"),
        (HEALTHY_URL, "请拖动滑块完成验证"),
    ],
)
def test_verification_states_stop_collection(url, body):
    with pytest.raises(VerificationRequired):
        assert_creator_center_ready(FakePage(url=url, body_text=body))


@pytest.mark.parametrize(
    "body",
    ["操作频繁", "访问受限", "请求过于频繁", "Forbidden"],
)
def test_access_restriction_markers_stop_collection(body):
    with pytest.raises(AccessBlocked):
        assert_creator_center_ready(FakePage(body_text=body))


def test_login_url_takes_precedence_over_body_challenge_markers():
    page = FakePage(
        url="https://creator.xiaohongshu.com/login",
        body_text="获取验证码 请完成安全验证 操作频繁",
    )

    with pytest.raises(AuthenticationRequired):
        assert_creator_center_ready(page)


def test_redirect_reason_401_takes_precedence_over_body_challenge_markers():
    page = FakePage(
        url=f"{HEALTHY_URL}?redirectReason=401",
        body_text="获取验证码 请完成人机验证",
    )

    with pytest.raises(AuthenticationRequired):
        assert_creator_center_ready(page)


def test_verification_url_takes_precedence_over_access_body_marker():
    page = FakePage(
        url="https://creator.xiaohongshu.com/verify",
        body_text="操作频繁",
    )

    with pytest.raises(VerificationRequired):
        assert_creator_center_ready(page)


@pytest.mark.parametrize(
    "body",
    [
        f"{HEALTHY_BODY} 内容标题：验证码功能说明 浏览量 20",
        f"{HEALTHY_BODY} 获取验证码的产品说明",
        f"{HEALTHY_BODY} 登录后可以查看更多历史数据",
    ],
)
def test_ordinary_creator_prose_does_not_signal_stop_state(body):
    assert_creator_center_ready(FakePage(body_text=body))


def test_forbidden_only_in_url_query_does_not_signal_access_block():
    page = FakePage(
        url=f"{HEALTHY_URL}?next=forbidden",
        body_text=HEALTHY_BODY,
    )

    assert_creator_center_ready(page)


def test_body_text_is_extracted_once_and_bounded_to_10000_characters():
    prefix = HEALTHY_BODY
    page = FakePage(
        body_text=prefix + "a" * (10_000 - len(prefix)) + "操作频繁"
    )

    assert_creator_center_ready(page)

    assert page.locator_calls == ["body"]
    assert len(page.evaluate_calls) == 1
    expression, limit = page.evaluate_calls[0]
    assert "innerText" in expression
    assert "slice" in expression
    assert limit == 10_000


def test_body_extraction_failure_is_wrapped():
    page = FakePage(body_error=RuntimeError("page detached"))

    with pytest.raises(BrowserNavigationError, match="page inspection failed") as exc_info:
        assert_creator_center_ready(page)

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_start_rejects_profile_path_through_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    config = replace(
        _config(tmp_path),
        profile_dir=linked_parent / "profile",
        download_dir=tmp_path / "downloads",
    )
    factory = FakePlaywrightFactory(FakePlaywright(FakeContext()))

    with pytest.raises(CollectorBrowserError, match="symlink"):
        BrowserSession(config, playwright_factory=factory).start()

    assert factory.calls == 0
    assert not (outside / "profile").exists()


def test_start_rejects_existing_file_as_private_directory(tmp_path):
    profile_file = tmp_path / "profile"
    profile_file.write_text("not a directory", encoding="utf-8")
    config = replace(
        _config(tmp_path),
        profile_dir=profile_file,
        download_dir=tmp_path / "downloads",
    )
    factory = FakePlaywrightFactory(FakePlaywright(FakeContext()))

    with pytest.raises(CollectorBrowserError, match="not a directory"):
        BrowserSession(config, playwright_factory=factory).start()

    assert factory.calls == 0


def test_start_rejects_existing_directory_owned_by_another_user(
    tmp_path, monkeypatch
):
    profile = tmp_path / "profile"
    profile.mkdir()
    config = replace(
        _config(tmp_path),
        profile_dir=profile,
        download_dir=tmp_path / "downloads",
    )
    original_stat = Path.stat

    def fake_stat(path, *args, **kwargs):
        if path == profile:
            actual = original_stat(path, *args, **kwargs)
            return SimpleNamespace(
                st_mode=actual.st_mode,
                st_uid=os.getuid() + 1,
            )
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)
    factory = FakePlaywrightFactory(FakePlaywright(FakeContext()))

    with pytest.raises(CollectorBrowserError, match="not owned by current user"):
        BrowserSession(config, playwright_factory=factory).start()

    assert factory.calls == 0


def test_start_rejects_private_directories_inside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = replace(
        _config(tmp_path),
        profile_dir=tmp_path / "profile",
        download_dir=tmp_path / "downloads",
    )
    factory = FakePlaywrightFactory(FakePlaywright(FakeContext()))

    with pytest.raises(CollectorBrowserError, match="outside repository"):
        BrowserSession(config, playwright_factory=factory).start()

    assert factory.calls == 0
    assert not config.profile_dir.exists()
    assert not config.download_dir.exists()


def test_start_only_chmods_configured_target_directories(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o755)
    state_dir.chmod(0o755)
    config = replace(
        _config(tmp_path),
        profile_dir=state_dir / "profile",
        download_dir=state_dir / "downloads",
    )
    context = FakeContext([FakePage()])
    session = BrowserSession(
        config,
        playwright_factory=FakePlaywrightFactory(FakePlaywright(context)),
    )

    session.start()

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o755
    assert stat.S_IMODE(config.profile_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.download_dir.stat().st_mode) == 0o700
