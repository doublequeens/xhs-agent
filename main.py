import argparse
import sys
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args
from uuid import uuid4

from langgraph.types import Command
from memory.memory_manager import XHSMemoryManager
from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.domain import DomainContext, DomainName, build_content_policy, get_domain_profile
from src.editorial_carousel.legacy import hydrate_legacy_editorial_state
from src.graph import create_graph
from src.models import set_default_provider
from src.nodes import node_p_text_card_renderer
from src.rendering.text_cards import output_paths
from src.run_registry import AgentRun, RunRegistry, RunRegistryError, exception_summary, format_run

SUPPORTED_DOMAINS = get_args(DomainName)
RUN_REGISTRY_PATH = Path("data/agent_runs.sqlite")
_LEGACY_DOMAIN_HYDRATION_WARNED = False
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LEGACY_IMAGE_PROMPT_FILENAME = "Storyboard_images_generator_prompt.txt"


def build_thread_id(explicit_id: str | None, now: datetime | None = None) -> str:
    if explicit_id is not None:
        return explicit_id
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"xhs_conversation_{timestamp}_{uuid4().hex}"


def build_run_config(thread_id: str | None) -> dict:
    return {"configurable": {"thread_id": build_thread_id(thread_id)}}


def hydrate_legacy_domain_state(values: dict) -> dict:
    global _LEGACY_DOMAIN_HYDRATION_WARNED

    domain_context = values.get("domain_context")
    if domain_context is not None:
        return {}

    profile = get_domain_profile("beauty", version="beauty-v1")
    updates = {
        "domain_context": DomainContext(
            domain="beauty",
            subdomain="skincare",
            classification_source="default",
            classification_confidence=1,
            profile_version=profile.version,
            risk_level="low",
        ),
        "content_policy": build_content_policy(profile, risk_level="low"),
    }

    if not _LEGACY_DOMAIN_HYDRATION_WARNED:
        warnings.warn(
            "Hydrating legacy domain checkpoint without domain_context using beauty/skincare defaults.",
            UserWarning,
            stacklevel=2,
        )
        _LEGACY_DOMAIN_HYDRATION_WARNED = True

    return updates


def load_run_state(graph, config: dict, initial_state: dict):
    current_state = graph.get_state(config)
    if current_state.values:
        editorial_updates = (
            hydrate_legacy_editorial_state(
                current_state.values,
                checkpoint_nodes=tuple(current_state.next),
            )
            if current_state.next
            else {}
        )
        hydration_updates = {
            **hydrate_legacy_domain_state(current_state.values),
            **editorial_updates,
        }
        if hydration_updates:
            graph.update_state(config, hydration_updates)
            current_state = graph.get_state(config)
    run_input = None if current_state.values else initial_state
    return current_state, run_input


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xiaohongshu Agent CLI")
    parser.add_argument("--domain", type=str, choices=SUPPORTED_DOMAINS, help="Explicit domain for routing")
    parser.add_argument("--subdomain", type=str, help="Explicit subdomain for the selected domain")
    run_group = parser.add_mutually_exclusive_group()
    run_group.add_argument("--new", action="store_true", help="Force a new agent run")
    run_group.add_argument("--resume", nargs="?", const="", metavar="RUN", help="Resume by run ID or thread ID")
    run_group.add_argument("--thread-id", type=str, help="Existing conversation thread ID to resume")
    parser.add_argument("--runs", action="store_true", help="List the latest 20 runs and exit")
    parser.add_argument("--verbose", action="store_true", help="Show full IDs in --runs output")
    parser.add_argument("--focus_keyword", type=str, help="Focus keyword for the post")
    parser.add_argument("--topic_num", type=int, default=10, help="Topic of the post")
    parser.add_argument("--provider", type=str, help="Model provider (glm, gemini, deepseek)")
    args = parser.parse_args() if argv is None else parser.parse_args(argv)
    if args.runs and (args.new or args.resume is not None or args.thread_id):
        parser.error("--runs cannot be combined with --new, --resume, or --thread-id")
    if args.subdomain and not args.domain:
        parser.error("--subdomain requires --domain")
    if args.domain and args.subdomain:
        profile = get_domain_profile(args.domain)
        if args.subdomain not in profile.allowed_subdomains:
            parser.error(
                "--subdomain must be one of "
                + ", ".join(profile.allowed_subdomains)
                + f" for domain {args.domain}"
            )
    return args


def create_initial_state(args: argparse.Namespace) -> dict:
    return {
        "interactive": True,
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "domain": args.domain,
        "subdomain": args.subdomain,
        "domain_context": None,
        "content_policy": None,
        "memory_context": None,
        "evidence_briefs": {},
        "final_policy_issues": [],
        "trends_num": args.topic_num,
        "focus_keyword": args.focus_keyword if args.focus_keyword else "",
        "topic_signals": [],
        "creative_briefs": [],
        "topic_candidates": [],
        "topic_generation_trace": None,
        "topic_generation_degraded_reason": None,
        "trends": [],
        "angles": [],
        "novelty_check_results": None,
        "scores": [],
        "outlines": [],
        "drafts": [],
        "title_options": [],
        "title_winner": None,
        "current_node": None,
        "decision_output": None,
        "r1_output": None,
        "r2_output": None,
        "final_content": None,
        "hashtags": None,
        "image_scripts": None,
        "image_candidates": None,
        "final_images": None,
        "visual_plan": None,
        "asset_manifest": None,
        "render_manifest": None,
        "publish_package": None,
        "review_status": None,
        "review_feedback": None,
        "review_round": 0,
        "review_route": None,
        "data_writed": None,
    }


def _value(item, name: str):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def extract_run_updates(values: dict, last_node: str | None = None) -> dict[str, str]:
    context = values.get("domain_context")
    package = values.get("publish_package") or {}
    trends = values.get("trends") or []
    candidate = _value(trends[0], "topic") if trends else None
    fields = {
        "domain": _value(context, "domain") or values.get("domain"),
        "subdomain": _value(context, "subdomain") or values.get("subdomain"),
        "title": _value(package, "title"),
        "topic_summary": _value(package, "topic") or candidate,
        "last_node": values.get("current_node") or last_node,
    }
    return {name: value for name, value in fields.items() if isinstance(value, str) and value}


def _print_run_choices(runs: list[AgentRun], output_fn=print) -> None:
    output_fn("\n可恢复的任务：")
    for run in runs:
        output_fn(format_run(run))
    output_fn("输入任务编号恢复；输入 n 新建任务；输入 q 退出。")


def select_run(registry: RunRegistry, args: argparse.Namespace, input_fn=input, output_fn=print):
    if args.new:
        thread_id = build_thread_id(None)
        registry.create_run(thread_id, args.focus_keyword)
        return thread_id, True
    if args.thread_id:
        return args.thread_id, False
    if args.resume not in (None, ""):
        run = registry.get_by_thread_id(args.resume)
        if run is None and args.resume.isdigit():
            run = registry.get_by_run_id(int(args.resume))
        if run is None:
            raise RunRegistryError(f"找不到要恢复的任务：{args.resume}")
        registry.update_run(run.thread_id, status="running", error_summary=None)
        return run.thread_id, False
    runs = registry.list_resumable()
    if not runs:
        thread_id = build_thread_id(None)
        registry.create_run(thread_id, args.focus_keyword)
        return thread_id, True
    _print_run_choices(runs, output_fn)
    while True:
        choice = input_fn("请选择：").strip().lower()
        if choice == "n":
            thread_id = build_thread_id(None)
            registry.create_run(thread_id, args.focus_keyword)
            return thread_id, True
        if choice == "q":
            return None
        if choice.isdigit():
            run = registry.get_by_run_id(int(choice))
            if run in runs:
                registry.update_run(run.thread_id, status="running", error_summary=None)
                return run.thread_id, False
        output_fn("无效选择，请输入列表中的任务编号、n 或 q。")


def backfill_legacy_run(registry: RunRegistry, thread_id: str, current_state) -> None:
    values = getattr(current_state, "values", None) or {}
    if not values or registry.get_by_thread_id(thread_id) is not None:
        return
    registry.upsert_run(thread_id, status="running", **extract_run_updates(values))


def _resolve_publish_package_profile(publish_package: dict):
    domain = publish_package.get("domain")
    profile_version = publish_package.get("profile_version")
    if not domain or not profile_version:
        raise ValueError("publish_package requires valid domain and profile_version metadata")

    try:
        return get_domain_profile(domain, version=profile_version)
    except ValueError as exc:
        raise ValueError(
            f"publish_package requires valid domain and profile_version metadata: {exc}"
        ) from exc


def _rendered_image_package_directory(publish_package: dict) -> tuple[Path, list[Path]]:
    """Validate the renderer's six-file output before writing the audit JSON."""
    raw_paths = publish_package.get("rendered_image_paths")
    expected_names = [path.name for path in output_paths(Path("images"))]
    if not isinstance(raw_paths, list) or len(raw_paths) != len(expected_names):
        raise ValueError("publish_package requires exactly six rendered_image_paths")

    publish_root = node_p_text_card_renderer.PUBLISH_ROOT.resolve()
    package_dir: Path | None = None
    resolved_paths: list[Path] = []
    for index, (raw_path, expected_name) in enumerate(zip(raw_paths, expected_names), start=1):
        try:
            image_path = Path(raw_path).resolve()
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(f"rendered image path {index} cannot be resolved: {exc}") from exc

        if not image_path.is_relative_to(publish_root):
            raise ValueError("rendered image paths must remain inside outputs/publish")
        if image_path.suffix.lower() != ".png":
            raise ValueError("rendered image paths must be PNG files")
        if image_path.name != expected_name:
            raise ValueError("rendered image paths must use the required sequence")
        if not image_path.is_file():
            raise ValueError(f"rendered image path is missing: {image_path.name}")
        try:
            png_signature = image_path.read_bytes()[: len(PNG_SIGNATURE)]
        except OSError as exc:
            raise ValueError(f"rendered image path cannot be read: {image_path.name}") from exc
        if png_signature != PNG_SIGNATURE:
            raise ValueError("rendered image paths must contain PNG files")
        if image_path.parent.name != "images":
            raise ValueError("rendered image paths must be inside the package images directory")

        current_package_dir = image_path.parent.parent
        if package_dir is None:
            package_dir = current_package_dir
        elif current_package_dir != package_dir:
            raise ValueError("rendered image paths must belong to one publish package")
        resolved_paths.append(image_path)

    assert package_dir is not None
    actual_pngs = sorted(path.resolve() for path in package_dir.joinpath("images").glob("*.png"))
    if actual_pngs != sorted(resolved_paths):
        raise ValueError("package images directory must contain exactly the rendered PNG sequence")
    return package_dir, resolved_paths


def export_publish_package(publish_package: dict) -> None:
    """Write an audit record alongside the locally rendered final card set."""
    _resolve_publish_package_profile(publish_package)
    package_dir, rendered_image_paths = _rendered_image_package_directory(publish_package)
    title = publish_package.get("title")
    if not isinstance(title, str) or not title:
        raise ValueError("publish_package requires a non-empty title for export")

    audit_path = (package_dir / f"{title}.json").resolve()
    if not audit_path.is_relative_to(package_dir):
        raise ValueError("publish audit path must remain inside the package directory")

    legacy_prompt_path = package_dir / LEGACY_IMAGE_PROMPT_FILENAME
    try:
        legacy_prompt_path.unlink(missing_ok=True)
    except OSError as exc:
        raise ValueError("obsolete image prompt could not be removed from package") from exc

    audit_package = dict(publish_package)
    audit_package["rendered_image_paths"] = [
        path.relative_to(package_dir).as_posix() for path in rendered_image_paths
    ]
    with audit_path.open("w", encoding="utf-8") as audit_file:
        json.dump(audit_package, audit_file, ensure_ascii=False, indent=4)


def read_multiline_json() -> dict:
    print("请粘贴完整 JSON，输入单独一行 END 结束：")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)

    return json.loads("\n".join(lines))


def collect_human_review(interrupt_value: dict) -> dict:
    publish_package = interrupt_value["publish_package"]
    pending_assets = list(interrupt_value.get("pending_assets") or [])
    asset_decisions = {}
    print("\n===== Human Review Required =====")
    print(interrupt_value["message"])
    print(json.dumps(publish_package, ensure_ascii=False, indent=2))

    for asset in pending_assets:
        decision_id = asset.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("Pending review asset is missing decision_id.")
        print(
            json.dumps(
                {
                    "slot_id": asset.get("slot_id"),
                    "provider": asset.get("provider"),
                    "provider_asset_id": asset.get("provider_asset_id"),
                    "source_url": asset.get("source_url"),
                    "author": asset.get("author"),
                    "license": asset.get("license"),
                    "license_terms_url": asset.get("license_terms_url"),
                    "sha256": asset.get("sha256"),
                    "metadata_path": asset.get("metadata_path"),
                    "unresolved_safety_checks": asset.get(
                        "unresolved_safety_checks"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        while True:
            decision = input(
                f"资产 {decision_id} ({asset.get('provider') or 'external'})："
                "输入 approved 或 rejected: "
            ).strip().lower()
            if decision in {"approved", "rejected"}:
                break
            print("无效输入，请输入 approved / rejected。")
        safety_decisions = {}
        if decision == "approved":
            for safety_check in list(asset.get("unresolved_safety_checks") or []):
                expected = safety_check == "allowed_for_publishing"
                while True:
                    answer = input(
                        f"安全项 {safety_check}：输入 yes 或 no: "
                    ).strip().lower()
                    if answer in {"yes", "no"}:
                        safety_decisions[safety_check] = answer == "yes"
                        break
                    print("无效输入，请输入 yes / no。")
                if safety_decisions[safety_check] is not expected:
                    raise ValueError(
                        f"Asset {decision_id} did not receive a safe publishing decision."
                    )
        asset_decisions[decision_id] = {
            "decision": decision,
            "binding": dict(asset.get("decision_binding") or {}),
            "safety_decisions": safety_decisions,
        }

    while True:
        action = input("\n输入 yes 继续；输入 edit 修改 JSON；输入 no 提建议并继续 review: ").strip().lower()

        if action == "yes":
            response = {
                "approved": True,
                "edited_publish_package": None,
                "feedback": "approved by user",
            }
            if asset_decisions:
                response["asset_decisions"] = asset_decisions
            return response

        if action == "edit":
            try:
                edited_publish_package = read_multiline_json()
            except json.JSONDecodeError as exc:
                print(f"JSON 解析失败：{exc}")
                continue

            approve = input("修改后是否批准继续？输入 yes 或 no: ").strip().lower()
            feedback = input("可选：补充一点 review 建议，直接回车可跳过: ").strip()
            response = {
                "approved": approve == "yes",
                "edited_publish_package": edited_publish_package,
                "feedback": feedback or "edited by user",
            }
            if asset_decisions:
                response["asset_decisions"] = asset_decisions
            return response

        if action == "no":
            feedback = input("请输入 review 建议: ").strip()
            response = {
                "approved": False,
                "edited_publish_package": None,
                "feedback": feedback,
            }
            if asset_decisions:
                response["asset_decisions"] = asset_decisions
            return response

        print("无效输入，请输入 yes / edit / no。")


def collect_domain_confirmation(interrupt_value: dict) -> dict:
    context = interrupt_value["context"]
    allowed_domains = tuple(interrupt_value.get("allowed_domains", SUPPORTED_DOMAINS))
    profile_subdomains = interrupt_value.get("allowed_subdomains")
    print("\n===== Domain Confirmation Required =====")
    print(interrupt_value["message"])
    print(json.dumps(context, ensure_ascii=False, indent=2))

    while True:
        selected_domain = (
            input(
                f"请输入 domain {allowed_domains}，直接回车使用当前值 {context['domain']}: "
            ).strip()
            or context["domain"]
        )
        if selected_domain not in allowed_domains:
            print("无效 domain，请重新输入。")
            continue

        if profile_subdomains is not None:
            allowed_subdomains = tuple(profile_subdomains)
            default_subdomain = (
                context["subdomain"]
                if selected_domain == context["domain"]
                and context["subdomain"] in allowed_subdomains
                else allowed_subdomains[0]
            )
        else:
            profile = get_domain_profile(selected_domain)
            allowed_subdomains = profile.allowed_subdomains
            default_subdomain = (
                context["subdomain"]
                if selected_domain == context["domain"]
                else profile.default_subdomain
            )
        print(f"可选 subdomain: {', '.join(allowed_subdomains)}")
        selected_subdomain = (
            input(f"请输入 subdomain，直接回车使用 {default_subdomain}: ").strip()
            or default_subdomain
        )
        if selected_subdomain not in allowed_subdomains:
            print("无效 subdomain，请重新输入。")
            continue

        return {"domain": selected_domain, "subdomain": selected_subdomain}


def collect_interrupt_response(interrupt_value: dict) -> dict:
    kind = interrupt_value.get("kind")
    if kind == "domain_confirmation":
        return collect_domain_confirmation(interrupt_value)
    if kind in {None, "publish_review"}:
        return collect_human_review(interrupt_value)
    raise ValueError(f"Unsupported interrupt kind: {kind}")


def export_completed_publish_package(graph, config) -> bool:
    """Export only from a completed, final-policy-clean graph checkpoint."""
    if not hasattr(graph, "get_state"):
        return False
    completed_state = graph.get_state(config)
    values = getattr(completed_state, "values", None) or {}
    if getattr(completed_state, "next", ()):
        return False
    if values.get("review_status") != "approved" or values.get("final_policy_issues"):
        return False
    publish_package = values.get("publish_package")
    if not publish_package:
        return False
    print("The final publish package title is:")
    print(publish_package["title"])
    export_publish_package(publish_package)
    return True


def sync_run_from_graph(
    registry: RunRegistry,
    graph,
    config: dict,
    thread_id: str,
    last_node: str | None,
) -> None:
    state = graph.get_state(config)
    values = getattr(state, "values", None) or {}
    registry.update_run(
        thread_id,
        status="running",
        error_summary=None,
        **extract_run_updates(values, last_node),
    )


def stream_graph_until_stop(
    graph,
    run_input,
    config,
    *,
    registry: RunRegistry | None = None,
    thread_id: str | None = None,
) -> bool:
    next_input = run_input

    while True:
        interrupted = False
        for output in graph.stream(next_input, config=config):
            for key, value in output.items():
                if key == "__interrupt__":
                    interrupted = True
                    interrupt_event = value[0]
                    payload = interrupt_event.value
                    if not isinstance(payload, dict):
                        raise ValueError("Interrupt payload must be a dict.")
                    if registry is not None and thread_id is not None:
                        registry.update_run(thread_id, status="awaiting_review")
                    next_input = Command(resume=collect_interrupt_response(payload))
                    if registry is not None and thread_id is not None:
                        registry.update_run(thread_id, status="running", error_summary=None)
                    break

                print(f"Finished processing node: {key}")
                if registry is not None and thread_id is not None:
                    sync_run_from_graph(registry, graph, config, thread_id, key)
            if interrupted:
                break

        if not interrupted:
            return export_completed_publish_package(graph, config)


def main():
    args = parse_cli_args()
    try:
        registry = RunRegistry(RUN_REGISTRY_PATH)
    except RunRegistryError as exc:
        print(f"本地运行注册表错误：{exc}", file=sys.stderr)
        sys.exit(1)

    thread_id = None
    try:
        if args.runs:
            for run in registry.list_recent(20):
                print(format_run(run, verbose=args.verbose))
            return

        selection = select_run(registry, args)
        if selection is None:
            return
        thread_id, is_new = selection

        init_message = "Starting Xiaohongshu Agent"
        if args.provider:
            init_message += f" with default model: {args.provider},"
        if args.focus_keyword:
            init_message += f" with topic focus keyword: {args.focus_keyword},"
        if args.domain:
            init_message += f" with domain: {args.domain},"
        if args.subdomain:
            init_message += f" with subdomain: {args.subdomain},"
        if args.topic_num:
            init_message += f" with topic number: {args.topic_num}."
        print(init_message)

        if args.provider:
            set_default_provider(args.provider)

        database = XHSMemoryManager("data/xhs_memory.db")
        database.init_db("memory/schema.sql")
        graph = create_graph()
        initial_state = create_initial_state(args)
        config = build_run_config(thread_id)
        current_state, run_input = load_run_state(graph, config, initial_state)

        if args.thread_id:
            backfill_legacy_run(registry, thread_id, current_state)
        if not current_state.values:
            if not is_new and args.resume is not None:
                raise RunRegistryError("所选任务的 LangGraph checkpoint 不存在，请使用 --new 创建新任务")
            if registry.get_by_thread_id(thread_id) is None:
                registry.create_run(thread_id, args.focus_keyword)
            print("No existing state found, starting a new run...")
        else:
            registry.update_run(
                thread_id,
                status="running",
                error_summary=None,
                **extract_run_updates(current_state.values),
            )
            print("Found existing state, resuming from the latest checkpoint...")

        if current_state.values and not current_state.next:
            if export_completed_publish_package(graph, config):
                registry.update_run(thread_id, status="completed", error_summary=None)
            else:
                registry.update_run(thread_id, status="awaiting_review")
            return

        exported = stream_graph_until_stop(
            graph,
            run_input,
            config,
            registry=registry,
            thread_id=thread_id,
        )
        if exported:
            registry.update_run(thread_id, status="completed", error_summary=None)
        else:
            registry.update_run(thread_id, status="awaiting_review")
    except Exception as exc:
        if thread_id is not None:
            try:
                if registry.get_by_thread_id(thread_id) is not None:
                    registry.update_run(
                        thread_id,
                        status="interrupted",
                        error_summary=exception_summary(exc),
                    )
            except RunRegistryError as registry_exc:
                print(f"本地运行注册表错误：{registry_exc}", file=sys.stderr)
        print(f"Error running agent: {exc}")
        sys.exit(1)
    finally:
        registry.close()

if __name__ == "__main__":
    main()
