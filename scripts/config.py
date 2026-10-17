

# ---------- 킬링타임용 가벼운 주제 (config.py 맨 아래에 추가) ----------
KO_QUERIES.update({
    "잡학": ["신기한 동물 특징", "동물 행동 특이", "음식 유래", "세계 기록", "이그노벨상"],
    "황당실화": ["황당한 사건", "이상한 법률", "기이한 전쟁", "역사상 기이한 사건", "엉뚱한 실화"],
    "흑역사": ["역사상 실패한 발명", "역사적 사기 조작", "대형 실수", "이상한 발명품"],
    "괴담": ["도시 전설", "괴생물 목격", "민담 괴담", "미확인 생물"],
    "착각": ["인지 편향", "착시 현상", "심리 효과", "기억 오류"],
    "인터넷": ["인터넷 밈 역사", "인터넷 유행어", "초기 인터넷 문화", "이모티콘 역사"],
})
EN_QUERIES.update({
    "잡학": ["unusual animal behavior", "origin of food", "world record oddity", "Ig Nobel Prize"],
    "황당실화": ["bizarre historical incident", "unusual law", "absurd war", "strange true story"],
    "흑역사": ["failed invention", "famous hoax", "historical blunder", "bizarre invention"],
    "괴담": ["urban legend", "cryptid sighting", "folklore creature", "haunted legend"],
    "착각": ["cognitive bias", "optical illusion", "psychological effect", "false memory"],
    "인터넷": ["internet meme history", "early internet culture", "viral video history", "emoticon history"],
})
RSS_FEEDS += [
    {"c": "황당실화", "name": "Damn Interesting", "url": "https://www.damninteresting.com/feed/"},
    {"c": "잡학", "name": "Futility Closet", "url": "https://www.futilitycloset.com/feed/"},
    {"c": "잡학", "name": "Today I Found Out", "url": "https://www.todayifoundout.com/index.php/feed/"},
    {"c": "인터넷", "name": "Boing Boing", "url": "https://boingboing.net/feed"},
]
# 너무 학술적이라 뺌
RSS_FEEDS[:] = [f for f in RSS_FEEDS if f["name"] != "Quanta Magazine"]
