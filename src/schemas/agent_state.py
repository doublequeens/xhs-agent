from typing import TypedDict, List, Optional
from .topic import TopicItem
from .angle import AngleStrategy
from .angle_score import ScoreResult
from .outline import OutlineItem
from .draft import DraftItem
from .title import DraftTitles
from .title_ranker import R1Input
from .r1_output import R1Output


class AgentState(TypedDict):
    trends: List[TopicItem]
    angles: List[AngleStrategy]
    scores: List[ScoreResult]
    outlines: List[OutlineItem]
    drafts: List[DraftItem]
    title_options: List[DraftTitles]
    title_winner: Optional[R1Input]
    r1_output: Optional[R1Output]
    r2_output: List[dict]
    hashtags: List[dict]
    image_scripts: List[dict]
    image_options: List[dict]
    image_selected: List[dict]
    publish_package: List[dict]
