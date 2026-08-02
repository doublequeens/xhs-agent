"""Task 16: ``content_writer_node`` on the ``llm_scene_v3`` dynamic-visual path.

The writer persists the visual-diversity memory metadata derived from the
dynamic visual contracts (no storyboard payload). It only writes after Human
Review approval + R2 compliance, and it must not read ``visual_plan`` or
``storyboards``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.nodes import node_p_content_writer as module
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    PageScene,
    ShapeElement,
    TextElement,
    TextStyle,
)
from src.schemas.visual_director import (
    PageDirection,
    VisualDirectionPlan,
)


# ---------------------------------------------------------------------------
# v3 contract fixture builders (mirrors tests/nodes/test_page_designer.py)
# ---------------------------------------------------------------------------


def _atom_set(page_count: int = 5) -> ContentAtomSet:
    texts = [f"第{index}页内容重点。" for index in range(1, page_count + 1)]
    atoms = tuple(
        ContentAtom(
            atom_id=f"atom-{index}",
            text=text,
            role="paragraph",
            sha256=sha256_text(text),
        )
        for index, text in enumerate(texts, start=1)
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def _fragments(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for index, atom in enumerate(atom_set.atoms, start=1)
    )


def _direction_plan(atom_set: ContentAtomSet) -> VisualDirectionPlan:
    fragments = _fragments(atom_set)
    return VisualDirectionPlan(
        template_family="soft_pink",
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="内容驱动的护肤编辑方向",
        palette=("#F4A7BF", "#FFFFFF", "#1A1A1A"),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("pink underlines",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个重点",
                visual_job=f"visual-job-{index}",
                fragment_ids=(f"fragment-{index}",),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=(),
    )


def _design_plan(
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
) -> CarouselDesignPlan:
    pages: list[PageScene] = []
    for direction_page in direction_plan.page_sequence:
        # Page 2 gets an extra shape element so density_summary varies per page.
        elements: list = [
            TextElement(
                element_id=f"text-{direction_page.page_id}",
                layer=1,
                box=Box(x=80, y=120, width=920, height=160),
                content_ref=direction_page.fragment_ids[0],
                style=TextStyle(
                    font_role="heading",
                    font_size=48,
                    line_height=1.3,
                    color="#1A1A1A",
                    align="left",
                    weight=700,
                ),
            )
        ]
        if direction_page.sequence == 2:
            elements.append(
                ShapeElement(
                    element_id=f"shape-{direction_page.page_id}",
                    layer=2,
                    box=Box(x=80, y=400, width=920, height=80),
                    shape="rectangle",
                    fill="#F4A7BF",
                )
            )
        background = "#FFFFFF" if direction_page.sequence % 2 == 1 else "#FFF0F4"
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background=background,
                elements=tuple(elements),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=tuple(pages),
    )


def _render_manifest(
    direction_plan: VisualDirectionPlan,
    *,
    source_root,
):
    # The writer only reads page count and per-page paths, so a lightweight
    # SimpleNamespace mirrors how the production state surfaces the manifest
    # without forcing the heavy RenderedElementProbe attestation here.
    pages = [
        SimpleNamespace(
            page_id=direction_page.page_id,
            sequence=direction_page.sequence,
            path=f"/tmp/{direction_page.page_id}.png",
        )
        for direction_page in direction_plan.page_sequence
    ]
    return SimpleNamespace(pages=pages)


def _asset_manifest() -> AssetManifest:
    return AssetManifest(items=())


def _topic(topic_id="tp_001"):
    return SimpleNamespace(
        topic_id=topic_id,
        domain="beauty",
        subdomain="skincare",
        content_intent="how_to",
        risk_level="low",
        risk_flags=["medical-adjacent"],
        content_contract={"first_screen_promise": "先看懂作息，再调整"},
    )


def _publish_package(**overrides) -> dict:
    package = {
        "topic_id": "tp_001",
        "topic": "分区护肤",
        "angle_id": "ag_001",
        "angle": "分区策略",
        "target_group": "通勤护肤人群",
        "core_pain": "分区不清",
        "title": "分区护肤指南",
        "cover_copy": "cover",
        "content": "正文",
        "hashtags": ["#护肤"],
        "content_contract": {"first_screen_promise": "先看懂分区"},
    }
    package.update(overrides)
    return package


def _v3_state(**overrides) -> dict:
    atom_set = _atom_set(5)
    direction_plan = _direction_plan(atom_set)
    manifest = _asset_manifest()
    design_plan = _design_plan(direction_plan, atom_set, manifest)
    render_manifest = _render_manifest(direction_plan, source_root=None)
    base = {
        "review_status": "approved",
        "trends": [_topic()],
        "publish_package": _publish_package(),
        "domain_context": {"profile_version": "beauty-v1"},
        "r2_output": SimpleNamespace(
            compliance_audit=SimpleNamespace(
                compliance_status="fully_compliant", block_publish=False
            )
        ),
        "content_atom_set": atom_set,
        "visual_direction_plan": direction_plan,
        "carousel_design_plan": design_plan,
        "render_manifest": render_manifest,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fake memory manager
# ---------------------------------------------------------------------------


class _FakeManager:
    def __init__(self, *args, **kwargs):
        self.saved_records = []
        self.embedding_records = []

    def init_db(self, schema_path):
        self.schema_path = schema_path

    def save_generated_content(self, record):
        self.saved_records.append(record)

    def save_embedding_content(self, record):
        self.embedding_records.append(record)

    def get_content_by_id(self, content_id):
        return {"content_id": content_id} if self.saved_records else None

    def get_embedding_content_by_id(self, content_id):
        return bool(self.embedding_records)


def _install_fake_manager(monkeypatch, fake_manager):
    monkeypatch.setattr(module, "XHSMemoryManager", lambda *a, **kw: fake_manager)
    monkeypatch.setattr(module, "make_content_id", lambda: "content-123")
    monkeypatch.setattr(module, "utc_now_iso", lambda: "2026-07-31T10:00:00+08:00")
    topic = _topic()
    monkeypatch.setattr(
        module,
        "get_topic_metadata",
        lambda _trends, _topic_id: {
            "domain": topic.domain,
            "subdomain": topic.subdomain,
            "content_intent": topic.content_intent,
            "risk_level": topic.risk_level,
            "risk_flags": list(topic.risk_flags),
        },
    )
    return fake_manager


# ---------------------------------------------------------------------------
# Approval / compliance gates
# ---------------------------------------------------------------------------


def test_content_writer_requires_approved_review_before_writing(monkeypatch):
    def fail_manager(*args, **kwargs):
        raise AssertionError("manager should not be constructed before approval")

    monkeypatch.setattr(module, "XHSMemoryManager", fail_manager)

    with pytest.raises(ValueError, match="approved"):
        module.content_writer_node({"review_status": "pending", "publish_package": {}})


def test_content_writer_requires_real_r2_compliance(monkeypatch):
    def fail_manager(*args, **kwargs):
        raise AssertionError("manager should not be constructed before R2 validation")

    monkeypatch.setattr(module, "XHSMemoryManager", fail_manager)

    with pytest.raises(ValueError, match="r2_output.compliance_audit.compliance_status"):
        module.content_writer_node(
            {
                "review_status": "approved",
                "trends": [_topic()],
                "publish_package": _publish_package(),
                "domain_context": {"profile_version": "beauty-v1"},
            }
        )


# ---------------------------------------------------------------------------
# v3 metadata derivation
# ---------------------------------------------------------------------------


def test_content_writer_derives_dynamic_visual_metadata_from_v3_contracts(monkeypatch):
    fake = _install_fake_manager(monkeypatch, _FakeManager())
    captured = {}
    fake.save_generated_content = lambda record: captured.setdefault("record", record)
    fake.saved_records.append  # keep _FakeManager API consistent

    atom_set = _atom_set(5)
    direction_plan = _direction_plan(atom_set)
    manifest = _asset_manifest()
    design_plan = _design_plan(direction_plan, atom_set, manifest)
    render_manifest = _render_manifest(direction_plan, source_root=None)

    module.content_writer_node(
        _v3_state(
            content_atom_set=atom_set,
            visual_direction_plan=direction_plan,
            carousel_design_plan=design_plan,
            render_manifest=render_manifest,
        )
    )

    record = captured["record"]
    assert record.page_count == 5
    assert record.template_family == "soft_pink"
    assert record.direction_signature == canonical_sha256(direction_plan)
    assert record.design_signature == canonical_sha256(design_plan)
    # density_summary is the per-page text-element count (page 2 has an extra
    # shape, but density tracks text elements => all 1 here).
    assert record.density_summary == [1, 1, 1, 1, 1]
    assert record.color_summary == {
        "palette": ["#F4A7BF", "#FFFFFF", "#1A1A1A"],
        "page_backgrounds": ["#FFFFFF", "#FFF0F4", "#FFFFFF", "#FFF0F4", "#FFFFFF"],
    }
    # The writer must not read or persist storyboard data on the v3 path.
    assert record.storyboards == []
    assert record.card_count == 5


def test_content_writer_does_not_read_storyboards_or_visual_plan(monkeypatch):
    """The v3 writer must derive page_count from render_manifest and must not
    touch ``visual_plan`` / ``storyboards`` keys at all."""

    fake = _install_fake_manager(monkeypatch, _FakeManager())
    captured = {}
    fake.save_generated_content = lambda record: captured.setdefault("record", record)

    state = _v3_state()
    # Poison the legacy keys to prove the writer never reads them.
    state["visual_plan"] = {"__probe__": "must-not-read"}
    state["publish_package"]["storyboards"] = [{"__probe__": "must-not-read"}]

    module.content_writer_node(state)

    record = captured["record"]
    assert record.page_count == 5
    assert record.storyboards == []


def test_content_writer_compensates_when_vector_write_fails(monkeypatch):
    class CompensationManager(_FakeManager):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.deleted_content_ids = []

        def save_embedding_content(self, record):
            raise RuntimeError("vector boom")

        def delete_content_by_id(self, content_id):
            self.deleted_content_ids.append(content_id)

    fake = _install_fake_manager(monkeypatch, CompensationManager())

    with pytest.raises(Exception, match="vector database chromadb"):
        module.content_writer_node(_v3_state())

    assert fake.deleted_content_ids == ["content-123"]
    assert fake.saved_records


def test_content_writer_returns_data_writed_flag_on_success(monkeypatch):
    fake = _install_fake_manager(monkeypatch, _FakeManager())

    result = module.content_writer_node(_v3_state())

    assert result == {"data_writed": True}
    assert fake.saved_records
    assert fake.embedding_records
