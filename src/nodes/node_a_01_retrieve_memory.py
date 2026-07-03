import os
import sys
from typing import Mapping

from src.schemas import AgentState
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from memory.memory_context import memory_context_to_prompt_payload
from memory.memory_manager import XHSMemoryManager

# MEMORY_MANAGER = XHSMemoryManager("../data/xhs_memory.db")
# MEMORY_MANAGER.init_db("../memory/schema.sql")


def _get_required_domain_scope(domain_context) -> tuple[str, str]:
    if isinstance(domain_context, Mapping):
        domain = domain_context.get("domain")
        subdomain = domain_context.get("subdomain")
    else:
        domain = getattr(domain_context, "domain", None)
        subdomain = getattr(domain_context, "subdomain", None)

    if not domain or not subdomain:
        raise ValueError(
            "retrieve_memory_node requires state.domain_context with domain and subdomain"
        )
    return domain, subdomain


def retrieve_memory_node(state: AgentState) -> dict:
    """
        A node that retrieves 14 days of recent memory context for content generation.
    
        Args:
            state (AgentState): The current state of the agent containing the memory manager instance.
        Returns:
            dict: A dictionary containing the memory context to be used in subsequent nodes.
    """

    # record = memory_manager.get_content_by_id(content_id)
    # if not record:
    #     raise ValueError(f"No content found with content_id: {content_id}")
    
    # memory_manager = XHSMemoryManager("../data/xhs_memory.db")
    # memory_manager.init_db("../memory/schema.sql")
    domain, subdomain = _get_required_domain_scope(state.get("domain_context"))
    database = XHSMemoryManager("data/xhs_memory.db")
    database.init_db("memory/schema.sql")

    memory_context = database.build_memory_context(
        domain=domain,
        subdomain=subdomain,
        recent_days=14,
    )
    memory_payload = memory_context_to_prompt_payload(memory_context)

    return {"memory_context": memory_payload}
