
import json

from examples.memory_demo import make_content_id
import memory
from memory.memory_manager import XHSMemoryManager, utc_now_iso
from memory.models import ContentRecord
from memory.vector_memory import XHSVectorMemory
from src.schemas.agent_state import AgentState

def content_writer_node(state: AgentState) -> AgentState:
    """
    A node that writes the final content to the database after assembly.

    Args:
        state (AgentState): The current state of the agent containing the final assembled content and memory manager instance.
    Returns:
        AgentState: The updated agent state.
    """

    database = XHSMemoryManager("data/xhs_memory.db")
    database.init_db("memory/schema.sql")

    publish_package = state.get("publish_package", {})  
    
    record = ContentRecord(
        content_id=make_content_id(),
        status="reviewed",
        created_at=utc_now_iso(),
        topic=publish_package["topic"],
        topic_id=publish_package["topic_id"],
        angle=publish_package["angle"],
        angle_id=publish_package["angle_id"],
        target_group=publish_package["target_group"],
        core_pain=publish_package["core_pain"],
        title=publish_package["title"],
        cover_copy=publish_package.get("cover_copy"),
        content=publish_package["content"],
        hashtags=publish_package["hashtags"],
        content_format="illustration",
        visual_style="hexagonal_dinosaur_fish_toothless",
        card_count=len(publish_package["storyboards"]),
        storyboards=publish_package["storyboards"],
        image_paths=[img["image_url"] for img in publish_package["images"]],
        compliance_status="fully_compliant",
        embedding_text=" ".join([
            publish_package["topic"],
            publish_package["angle"],
            publish_package["target_group"],
            publish_package["core_pain"],
            publish_package["title"],
            " ".join(publish_package["hashtags"]),
        ]),
    )
    # save structured content to database
    try:
        database.save_generated_content(record)
    except Exception as e:
        raise Exception(f"Error occurred while saving generated content to structured database sqlite: {e}")

    # save semantic embedding content to vector database
    try:
        database.save_embedding_content(record)
    except Exception as e:
        raise Exception(f"Error occurred while saving generated content to vector database chromadb: {e}")
    
    if database.get_content_by_id(record.content_id) and database.get_embedding_content_by_id(record.content_id):
        print(f"Content with ID {record.content_id}, with title {record.title} successfully saved to the structured and embedding database.")
        return {"data_writed": True}
    
    return {"data_writed": False}