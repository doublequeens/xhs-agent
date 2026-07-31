def test_visual_migration_keeps_required_public_handoff_exports():
    from src.schemas import AgentState, CarouselPayload
    from src.schemas.agent_state import AgentState as DefinedAgentState
    from src.schemas.storyboard import CarouselPayload as DefinedCarouselPayload

    assert AgentState is DefinedAgentState
    assert CarouselPayload is DefinedCarouselPayload
