import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.nodes.node_j_decision_engine import decision_engine_node

# 1. 构造一个 mock_state (根据你的 AgentState 结构伪造假数据)
mock_state = {
    "current_node": "TITLE_RANKER",
    "title_winner": {
        'draft_id': 'outline_001',
        'draft_md': '我当时真的以为，这瓶大几百的粉底液跟我八字不合…\n\n每次涂完防晒再上底妆，脸上就像在搓泥巴，斑驳得没法看😭\n差点一气之下把它扔进垃圾桶！\n\n后来被一个化妆师朋友点醒才发现\n根本不是底妆的锅！\n是我涂防晒的手法太野蛮了🙃\n\n大家回想一下，自己涂防晒是不是像涂面霜一样？\n在脸上疯狂打圈揉搓？\n这就对了，防晒里的成膜剂全被你搓破了！\n膜都破了，后续上粉底能不打架吗？\n\n其实只要换个手法，90%的搓泥问题都能解决👇\n\n千万别再画圈圈了！防晒要“顺毛捋”！\n\n先把防晒分区点涂在脸上\n然后顺着咱们脸上的毛孔方向，单向平铺开\n遇到边缘没涂匀的地方，用指腹轻轻拍打按压\n主打一个轻柔，千万别来回蹭！\n\n涂完之后，别急着立马怼粉底液⚠️\n去挑个衣服或者刷个牙，给防晒1-2分钟的成膜时间\n怎么判断成膜了？\n用手背轻轻碰一下脸，不黏糊糊的就说明可以上妆啦！\n\n帮大家理了一个绝不搓泥的傻瓜操作清单，建议直接截图照做：\n\n👉 用量：一元硬币大小才够防晒力\n👉 手法：分区涂，顺毛孔，不打圈，边缘轻按压\n👉 等待：涂完等个1-2分钟干透\n👉 底妆：最好用微湿美妆蛋拍开，别用刷子扫\n\n只要顺着这个逻辑来，底妆服帖一整天不是梦✨\n\n你平时哪支防晒或者粉底液让你觉得疯狂搓泥？\n来评论区吐槽，我帮你看看是不是手法踩坑了！',
        'best_title': '别再打圈涂防晒了！难怪底妆天天搓泥',
        'best_title_id': 'outline_001_01',
        'safer_title': '很多人都做错！防晒当面霜涂后续铁定搓泥',
        'safer_title_id': 'outline_001_06',
        'best_cover_copy': '别再打圈涂防晒了！',
        'why_win': ['痛点极度高频，几乎所有化妆人群都经历过防晒底妆打架的困扰',
        '切入点具有强烈的反常识属性（防晒不能打圈涂），能瞬间打破读者固有认知，引发好奇和点击',
        '给出的解决方案（顺毛平铺、等待成膜）低成本且立竿见影，读者获得感和可保存价值极高',
        '行文结构完美契合小红书爆款逻辑（共情痛点 -> 认知纠偏 -> 实操清单 -> 互动提问）'],
        'must_fix_if_selected': [{'rec_id': 'rk_fix_winner_01',
        'instruction': '修改绝对化数据表达',
        'severity': 'medium',
        'location_hint': 'draft_md',
        'rationale': '“90%”属于具体数据，若无权威出处可能触发平台数据夸大审核',
        'before': '其实只要换个手法，90%的搓泥问题都能解决👇',
        'after_hint': '替换为“大部分的搓泥问题都能解决”或“大大减少搓泥概率”'}],
        'optional_improvements': [{'rec_id': 'rk_opt_winner_01',
        'instruction': '优化防晒用量描述',
        'severity': 'low',
        'location_hint': 'draft_md',
        'rationale': '不同防晒密度不同，一元硬币大小较为笼统，可增加更严谨的描述',
        'before': '👉 用量：一元硬币大小才够防晒力',
        'after_hint': '改为“约一枚硬币大小（具体视防晒质地而定）”'},
        {'rec_id': 'rk_opt_winner_02',
        'instruction': '增加具体产品避雷/种草互动',
        'severity': 'low',
        'location_hint': 'draft_md',
        'rationale': '引导用户分享具体产品名，能大幅增加评论区的讨论热度和干货密度',
        'before': '你平时哪支防晒或者粉底液让你觉得疯狂搓泥？',
        'after_hint': '改为“你平时哪支防晒或者粉底液让你觉得疯狂搓泥？直接带名字来评论区吐槽，我帮你看看是不是手法踩坑了！”'}],
        'topic_id': 'tp_002',
        'topic': '防晒搓泥大拯救：底妆打架原来是涂法惹的祸',
        'angle_id': 'ag_001',
        'angle': '认知纠偏：防晒上脸手法误区',
        'target_group': '日常通勤党、有化妆需求的早八人',
        'core_pain': '涂完防晒再上粉底，脸上搓出泥条，妆面斑驳不服帖'
    }
}

# 2. 直接调用该节点并打印结果
result = decision_engine_node(mock_state)
print(result)
