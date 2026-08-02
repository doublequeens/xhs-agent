"""Beauty-account workflow integration for the ``llm_scene_v3`` pipeline.

Replaces the pre-v3 ``storyboard`` workflow test (deleted with the fixed-card
renderer in the Task 17 cleanup) with its v3 successor: the commuting-beauty
account's skincare copy -- including the persistent-pain / redness / tightness
self-check line -- is atomized by the REAL ``content_atomizer``, routed through
the REAL dynamic visual chain (scripted fakes for the four structured-model
nodes only), and reaches Human Review -> Final Guard -> content_writer with the
beauty domain context and focus keyword preserved.

Intent preserved from the deleted v2 test:
* the beauty account contract (domain=beauty, subdomain=skincare, focus keyword
  防晒搓泥) flows end-to-end;
* assembler/audit noise (notes like "仅供参考", "AI生成示意图") NEVER enters the
  visible atom set -- the content atomizer rebuilds atoms only from the locked
  title/cover_copy/content;
* every produced carousel page is a real 1080x1440 PNG.
"""

from __future__ import annotations

from pathlib import Path

from src.nodes.node_p_content_atomizer import build_content_atoms
from tests.dynamic_visual.golden_fixtures import CaseSpec, GoldenHarness

COMMUTING_BEAUTY_TITLE = "通勤防晒不搓泥"
COMMUTING_BEAUTY_COVER = "三步避开搓泥"
COMMUTING_BEAUTY_CONTENT = "\n".join(
    [
        "1. 防晒取一元硬币大小，均匀涂全脸",
        "2. 等待三分钟让防晒成膜",
        "3. 再上底妆，减少搓泥堆积",
        "出现持续刺痛、明显泛红或第二天仍然紧绷时暂停新品",
        "鼻翼发际线不要漏涂，每两小时补涂一次",
    ]
)


def _beauty_spec(case_id: str = "beauty-account") -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        family="pink_red",
        page_count=7,  # title + cover + 5 content atoms
        density="standard",
        copy_shape="tutorial",
        asset_mode="text-only",
        note="commuting beauty women; persistent pain/redness/tightness",
        publish_package={
            "topic_id": "tp_sunscreen_commute",
            "angle_id": "ag_sunscreen_order",
            "topic": "通勤防晒底妆不搓泥",
            "angle": "防晒与底妆顺序",
            "target_group": "通勤上班族",
            "core_pain": "防晒后底妆搓泥",
            "focus_keyword": "防晒搓泥",
            "title": COMMUTING_BEAUTY_TITLE,
            "cover_copy": COMMUTING_BEAUTY_COVER,
            "content": COMMUTING_BEAUTY_CONTENT,
            "hashtags": ["#通勤底妆", "#防晒搓泥"],
            "domain": "beauty",
            "subdomain": "skincare",
            "content_contract": {
                "first_screen_promise": "通勤前三步避开防晒搓泥",
            },
        },
        human_review_payload={"approved": True},
    )


def test_beauty_account_copy_atomizes_without_assembler_noise(tmp_path, monkeypatch):
    """The content atomizer rebuilds the visible atom set ONLY from the locked
    title/cover_copy/content. Assembler-style notes (仅供参考 / AI生成示意图)
    that used to leak via the old assembler/audit path must never appear in the
    atoms, even if they were present in surrounding state."""
    spec = _beauty_spec()
    harness = GoldenHarness(spec=spec, tmp_path=tmp_path)
    state = harness.run(monkeypatch)

    atom_set = state["content_atom_set"]
    atom_texts = [atom.text for atom in atom_set.atoms]
    expected = [
        atom.text
        for atom in build_content_atoms(
            title=COMMUTING_BEAUTY_TITLE,
            cover_copy=COMMUTING_BEAUTY_COVER,
            content=COMMUTING_BEAUTY_CONTENT,
        )
    ]
    assert atom_texts == expected

    # The persistent-pain / redness / tightness line survives atomization as
    # exactly one atom (the account's signature self-check).
    pain_atom = [
        text for text in atom_texts
        if "持续刺痛" in text and "泛红" in text and "紧绷" in text
    ]
    assert len(pain_atom) == 1

    # No forbidden assembler/audit noise anywhere in the visible atoms.
    forbidden = ("仅供参考", "AI生成", "示意图", "免责声明")
    assert all(not any(token in text for token in forbidden) for text in atom_texts)


def test_beauty_account_reaches_final_guard_with_domain_contract(
    tmp_path, monkeypatch
):
    """The beauty account carousel reaches Final Guard -> content_writer with
    the beauty domain context and focus keyword preserved through the v3 chain.
    """
    spec = _beauty_spec()
    harness = GoldenHarness(spec=spec, tmp_path=tmp_path)
    state = harness.run(monkeypatch)

    assert state.get("review_status") == "approved"
    assert state.get("final_policy_issues") == []
    assert state["visual_direction_plan"].template_family == "pink_red"

    render_manifest = state["render_manifest"]
    assert len(render_manifest.pages) == 7
    for page in render_manifest.pages:
        assert page.width == 1080 and page.height == 1440
        assert Path(page.path).is_file()

    package = state["publish_package"]
    assert package["focus_keyword"] == "防晒搓泥"
    assert package["domain"] == "beauty"
    assert package["subdomain"] == "skincare"
