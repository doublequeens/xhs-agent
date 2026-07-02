from .models import DomainProfile

EVIDENCE_DOMAINS = ("who.int", "nih.gov", "cdc.gov", "nhs.uk", "nhc.gov.cn", "chinacdc.cn")
PROHIBITED_TOPICS = ("疾病诊断", "治疗方案", "药物建议", "检查指标解读", "个体化处方")
PROHIBITED_CLAIMS = ("保证有效", "根治", "永久改善", "立即见效", "替代治疗")

PROFILES: dict[str, DomainProfile] = {
    "beauty": DomainProfile(
        domain="beauty",
        version="beauty-v1",
        default_subdomain="skincare",
        allowed_subdomains=("skincare", "haircare", "bodycare", "makeup_basics"),
        keyword_map={
            "skincare": ("护肤", "防晒", "保湿", "清洁", "抗老"),
            "haircare": ("护发", "头发", "发质"),
            "bodycare": ("身体护理", "身体乳"),
            "makeup_basics": ("美妆", "化妆", "底妆"),
        },
        prohibited_topics=PROHIBITED_TOPICS,
        prohibited_claims=PROHIBITED_CLAIMS,
        required_disclaimers=("内容仅作一般美容与生活方式分享",),
        hashtag_seeds=("美容", "护肤", "日常护理"),
        visual_guidelines=("使用日常护理和真实生活场景",),
        evidence_domains=EVIDENCE_DOMAINS,
    ),
    "wellness": DomainProfile(
        domain="wellness",
        version="wellness-v1",
        default_subdomain="daily_routine",
        allowed_subdomains=("sleep", "stress_management", "daily_routine", "recovery"),
        keyword_map={
            "sleep": ("睡眠", "熬夜", "早睡", "失眠"),
            "stress_management": ("压力", "放松", "情绪"),
            "daily_routine": ("养生", "作息", "习惯"),
            "recovery": ("恢复", "休息", "疲劳"),
        },
        prohibited_topics=PROHIBITED_TOPICS,
        prohibited_claims=PROHIBITED_CLAIMS,
        required_disclaimers=("内容仅作一般生活方式科普",),
        hashtag_seeds=("养生习惯", "睡眠管理", "生活方式"),
        visual_guidelines=("使用睡眠、通勤、休息和居家场景",),
        evidence_domains=EVIDENCE_DOMAINS,
    ),
    "healthy_lifestyle": DomainProfile(
        domain="healthy_lifestyle",
        version="healthy-lifestyle-v1",
        default_subdomain="daily_habits",
        allowed_subdomains=(
            "nutrition_basics",
            "exercise",
            "hydration",
            "sedentary_habits",
            "daily_habits",
        ),
        keyword_map={
            "nutrition_basics": ("饮食", "营养", "早餐", "蔬菜"),
            "exercise": ("运动", "健身", "走路", "拉伸"),
            "hydration": ("喝水", "补水", "饮水"),
            "sedentary_habits": ("久坐", "办公"),
            "daily_habits": ("健康", "生活习惯"),
        },
        prohibited_topics=PROHIBITED_TOPICS,
        prohibited_claims=PROHIBITED_CLAIMS,
        required_disclaimers=("内容仅作一般健康生活方式科普",),
        hashtag_seeds=("健康生活", "生活习惯", "健康科普"),
        visual_guidelines=("使用饮食、运动、饮水和办公生活场景",),
        evidence_domains=EVIDENCE_DOMAINS,
    ),
}
