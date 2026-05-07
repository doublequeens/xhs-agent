from __future__ import annotations

import sqlite3
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memory.memory_manager import XHSMemoryManager, utc_now_iso
from memory.models import ContentRecord
from memory.memory_context import memory_context_to_prompt_payload

def add_column_to_db():
    db_path = Path("data/xhs_memory.db")
    if not db_path.exists():
        print("数据库文件不存在！请检查路径。")
        return

    # 连接数据库
    conn = sqlite3.connect(db_path)
    try:
        # 执行添加新列的操作
        conn.execute("ALTER TABLE contents ADD COLUMN storyboards TEXT;")
        conn.commit()
        print("✅ 成功在 contents 表中添加了 storyboards 列！")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("⚠️ storyboards 列已经存在，无需重复添加。")
        else:
            print(f"❌ 发生错误: {e}")
    finally:
        conn.close()


def make_content_id() -> str:
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    return f"local_{now}_{uuid.uuid4().hex[:6]}"


def main() -> None:
    memory = XHSMemoryManager("data/xhs_memory.db")
    memory.init_db("memory/schema.sql")

    content_id = make_content_id()

    record = ContentRecord(
        content_id=content_id,
        status="published",
        created_at=utc_now_iso(),
        topic_id="test_002",
        topic="防晒避坑",
        angle_id="ag_002",
        angle="防晒怎么涂",
        target_group="日常上班族",
        core_pain="防晒搓泥闷痘",
        title="别催！涂完防晒等这步，不然真白涂",
        cover_copy="防晒避坑",
        content="啊啊啊原来我之前的防晒都白涂了！😭\n\n一直以为随便抹匀就行，结果脸颊闷出了小颗粒，还以为是自己没洗干净脸……\n\n后来才发现，防晒的“成膜法则”和涂抹手法，才是决定防不防晒黑、长不长闭口的关键！❌\n\n---\n\n⚠️ 涂完防晒马上就上妆？难怪防晒白涂！\n防晒霜是需要时间形成保护膜的！你立刻上粉底，膜全被破坏了——\n\n不仅防紫外线能力大跳水🆘\n还特别容易跟底妆打架、搓泥、起屑屑！\n\n---\n\n那到底要等多久？⌛️\n建议静置3-5分钟！等感觉脸上干爽不粘手了，这才算成膜完毕！💡\n\n💥 重点来了！\n涂防晒一定要顺着同一个方向轻轻推开，尽量不打圈揉搓！\n\n等成膜后，用粉扑轻轻按压上妆，尽量避免横向摩擦脸蛋！\n\n---\n\n看完是不是有点乱？别急！我直接给你总结了【防晒不踩雷的3步法则】👇\n\n✅ **用量要足**：建议挤出一元硬币大小（别心疼！）\n✅ **手法要对**：单向平铺，尽量不打圈\n✅ **耐心要够**：静置3-5分钟，干爽后再上底妆\n\n记住这个九字真言就够啦👏\n👉 **“足量、单向、等成膜”**\n告别搓泥和小颗粒真的不难！📌\n\n---\n\n最后，宝子们注意！\n如果脸上闭口或者颗粒问题真的很严重，一定要先去看医生哦！🩺\n\n---\n\n你平时涂防晒会等成膜吗？一般等几分钟？来评论区聊聊！😉",
        hashtags=["#防晒怎么涂",
        "#防晒成膜",
        "#防晒搓泥",
        "#防晒白涂",
        "#妆前护肤",
        "#长闭口",
        "#防晒避坑",
        "#护肤新手"],
        content_format="illustration",
        visual_style="hexagonal_dinosaur_fish_toothless",
        card_count=6,
        storyboards=["a", "b", "c", "d", "e", "f"],
        image_paths=[],
        strategy_tags=[],
        compliance_status="fully_compliant",
        embedding_text="防晒避坑 防晒怎么涂 日常上班族 防晒搓泥闷痘 别催！涂完防晒等这步，不然真白涂",
        metadata={
            "agent_version": "0.1.0",
            "workflow": "memory_demo",
        },
    )

    memory.save_generated_content(record)

    memory.mark_published(
        content_id=content_id,
        post_id="xhs_699xxxx",
        url="https://www.xiaohongshu.com/discovery/item/example",
    )

    metrics = memory.update_metrics(
        content_id=content_id,
        views=528,
        likes=0,
        saves=0,
        comments=0,
        shares=0,
        followers_gained=0,
    )

    print("Metrics:")
    print(metrics)

    context = memory.build_memory_context()
    prompt_payload = memory_context_to_prompt_payload(context)

    print("\nMemory Context for Prompt:")
    print(prompt_payload)

def delete_record(content_id: str) -> None:
    memory = XHSMemoryManager("data/xhs_memory.db")
    memory.init_db("memory/schema.sql")
    memory.delete_content_by_id(content_id)
    print(f"Content with ID {content_id} has been deleted.")

def mark_published(content_id: str, post_id: str, url: str, published_at: str = None) -> None:
    memory = XHSMemoryManager("data/xhs_memory.db")
    memory.init_db("memory/schema.sql")
    memory.mark_published(
        content_id=content_id,
        post_id=post_id,
        url=url,
        published_at=published_at
    )
    print(f"Content with ID {content_id} has been marked as published with post ID {post_id} and URL {url}.")

def update_record_metrics(content_id: str, post_id: str, url: str, views: int, likes: int, saves: int, comments: int, shares: int, followers_gained: int) -> None:
    memory = XHSMemoryManager("data/xhs_memory.db")
    memory.init_db("memory/schema.sql")
    # memory.update_content_field(content_id, "title", "新的标题：别催！涂完防晒等这步，不然真白涂")

    metrics = memory.update_metrics(
        content_id=content_id,
        views=views,
        likes=likes,
        saves=saves,
        comments=comments,
        shares=shares,
        followers_gained=followers_gained,
    )
    print(f"Content with ID {content_id} has been updated.")
    print("Metrics:")
    print(metrics)

if __name__ == "__main__":
    # add_column_to_db()
    # main()
    # delete_record("local_20260505_134002_685564")
    # mark_published(content_id="local_20260507_120221_206a67", 
    #                post_id="69fc13ab000000001f000247", 
    #                url="https://www.xiaohongshu.com/explore/69fc13ab000000001f000247?xsec_token=YBochRtxIIVsUtnMci7Yu695Mx7ueDkXLeFPO0SU0eb0k%3D&xsec_source=pc_creatormng",
    #                )
    update_record_metrics(
        content_id="local_20260506_083957_9538fe",
        post_id="69fb1e4f000000003603352c",
        url="https://www.xiaohongshu.com/explore/69fb1e4f000000003603352c?xsec_token=YBNzxnoTinfuy8Smb3pskbuZJ-jOdNouPO-yrJKyG3Cuc%3D&xsec_source=pc_creatormng",
        views=11,
        likes=0,
        saves=0,
        comments=0,
        shares=0,
        followers_gained=0,
    )