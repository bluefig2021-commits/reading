#!/usr/bin/env python3
"""랜덤 지식 TV 수집기.

위키백과(한국어) 검색 + RSS 에서 글감을 가져와서
(ANTHROPIC_API_KEY 가 있으면) AI로 짧게 줄이고, data/items.json 에 추가한다.

- 원문 전체를 복사하지 않는다. 짧은 요약 + 출처 + 원문 링크만 저장한다.
- AI에게는 가져온 텍스트 안의 내용만 쓰라고 시킨다 (지어내기 방지).
- 이미 있는 글(같은 url)은 다시 안 넣는다.

사용:  python scripts/collect.py            (실제 저장)
       python scripts/collect.py --dry-run  (저장 안 하고 결과만 출력)
"""
import hashlib
import html
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "items.json")

UA = "RandomKnowledgeTV/1.0 (personal hobby project)"
MAX_ITEMS = 5000
PER_CAT = int(os.environ.get("PER_CAT", "5"))          # 카테고리당 한 번에 추가할 개수
MODEL = os.environ.get("MODEL", "claude-haiku-5-5")      # 안 되면 모델 이름 바꿔
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DRY = "--dry-run" in sys.argv

# 위키백과 검색어. 여기에 계속 추가하면 글감이 넓어진다.
KO_QUERIES = {
    "미스터리": ["미해결 미스터리 실종", "정체불명 신호", "유령선", "미스터리 유물"],
    "미제사건": ["미제 사건 살인", "미해결 사건 범인 불명", "연쇄 살인 미제", "공소시효 만료 사건"],
    "고대문명": ["고대 문명 유적", "해독되지 않은 문자", "거석 유적", "고대 유물 발굴"],
    "미학": ["미학 개념", "미술 기법", "일본 전통 미의식", "안료 색채 역사", "건축 양식"],
    "과학": ["신기한 과학 현상", "천문학 발견", "생물학 동물 특이"],
    "AI·미래": ["인공지능 역사", "기술적 특이점", "뇌 컴퓨터 인터페이스", "미래학 미래 기술"],
    "역사": ["역사 사건 기록", "조선 시대 제도", "고대 로마 역사"],
    "사건사고": ["대형 사고 원인", "항공 사고", "산업 재해 역사"],
    "IT": ["컴퓨터 역사", "인터넷 역사", "프로그래밍 언어 역사"],
    "문학": ["고전 소설", "세계 문학 작품"],
    "인물": ["철학자 사상가", "화가 미술가 생애", "작곡가 음악가 생애", "시인 소설가 작가", "역사 인물 군주 정치가",
             "과학자 업적", "건축가 조각가", "수학자 물리학자", "탐험가 발명가"],
    "영화": ["SF 영화", "공상과학 영화 명작", "디스토피아 영화", "고전 영화 걸작", "영화 역사 명작", "우주 영화"],
}

EN_QUERIES = {
    "미스터리": ["unsolved mystery disappearance", "unexplained phenomenon", "ghost ship", "mysterious artifact"],
    "미제사건": ["unsolved murder case", "cold case unidentified killer", "famous unsolved crime", "unsolved disappearance"],
    "고대문명": ["ancient civilization archaeological site", "undeciphered writing system", "megalithic monument", "ancient technology artifact"],
    "미학": ["aesthetics concept", "painting technique art history", "japanese aesthetics", "history of pigments"],
    "과학": ["scientific discovery history", "strange animal behavior", "astronomy discovery", "physics paradox"],
    "AI·미래": ["history of artificial intelligence", "technological singularity", "brain computer interface", "future technology concept"],
    "역사": ["forgotten history event", "lost city history", "historical hoax"],
    "사건사고": ["famous disaster investigation", "industrial accident history", "aviation accident cause"],
    "IT": ["history of computing", "history of the internet"],
    "문학": ["classic novel", "world literature masterpiece"],
    "인물": ["philosopher thought", "painter life", "composer life", "poet novelist", "historical figure ruler"],
    "영화": ["science fiction film classic", "dystopian film", "cult film history"],
}

# 영어 위키는 AI 번역이 필요해서 ANTHROPIC_API_KEY 없으면 건너뜀
WIKI_SOURCES = [
    {"host": "ko.wikipedia.org", "lang": "ko", "name": "한국어 위키백과 (CC BY-SA 4.0)", "queries": KO_QUERIES},
    {"host": "en.wikipedia.org", "lang": "en", "name": "영어 위키백과 (CC BY-SA 4.0)", "queries": EN_QUERIES},
]

# 인물 카테고리 필터: 예술/철학/학문/역사 인물만, 이미 세상을 떠난 사람만, 연예/스포츠 제외
PERSON_OK = ["철학자", "사상가", "화가", "미술가", "조각가", "건축가", "작곡가", "음악가", "시인", "소설가",
             "작가", "극작가", "역사가", "사학자", "수학자", "물리학자", "화학자", "천문학자", "과학자",
             "발명가", "탐험가", "정치가", "군주", "왕", "황제", "장군", "학자", "신학자", "사진가",
             "디자이너", "예술가", "저술가", "비평가", "문학가", "승려", "성직자"]
PERSON_BLOCK = ["가수", "배우", "아이돌", "탤런트", "방송인", "연기자", "모델", "코미디언", "개그맨", "개그우먼",
                "예능", "유튜버", "스트리머", "래퍼", "걸그룹", "보이그룹", "축구", "야구", "농구", "배구",
                "골프", "테니스", "격투", "레슬링", "올림픽", "운동선수", "체육인"]
DEAD_RE = re.compile(r"\d{1,4}년[^)]{0,30}[~–\-―][^)]{0,30}\d{1,4}년")

PERSON_OK_EN = ["philosopher", "painter", "composer", "poet", "novelist", "writer", "playwright", "mathematician",
                "physicist", "chemist", "astronomer", "scientist", "inventor", "explorer", "emperor", "king",
                "queen", "general", "architect", "sculptor", "theologian", "historian", "artist", "photographer",
                "statesman", "pharaoh", "mystic", "essayist", "critic"]
PERSON_BLOCK_EN = ["singer", "actor", "actress", "footballer", "baseball", "basketball", "rapper", "television",
                   "comedian", "athlete", "olympic", "youtuber", "streamer", "influencer", "boxer", "wrestler",
                   "golfer", "tennis", "racing driver", "pop star"]
DEAD_RE_EN = re.compile(r"\([^)]{0,60}\d{3,4}[^)]{0,10}[–—\-][^)]{0,40}\d{3,4}[^)]*\)")


def person_ok(desc, text, lang="ko"):
    desc = desc or ""
    if lang == "en":
        head = (desc + " " + text[:200]).lower()
        if any(w in head for w in PERSON_BLOCK_EN):
            return False
        if not any(w in (desc or text[:150]).lower() for w in PERSON_OK_EN):
            return False
        return bool(DEAD_RE_EN.search(text[:200]))
    head = desc + " " + text[:200]
    if any(w in head for w in PERSON_BLOCK):
        return False
    if not any(w in (desc or text[:150]) for w in PERSON_OK):
        return False
    return bool(DEAD_RE.search(text[:150]))


# RSS (영어 글은 AI 요약/번역이 있을 때만 사용). 주소가 바뀌었거나 안 열리면 로그에 "RSS 실패"로 뜨고 그냥 건너뜀.
# 제목 + 짧은 요약 + 원문 링크만 쓰는 용도야. 각 사이트 이용 조건은 직접 확인해.
PER_FEED = int(os.environ.get("PER_FEED", "2"))
RSS_FEEDS = [
    {"c": "AI·미래", "name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
    {"c": "AI·미래", "name": "OpenAI News", "url": "https://openai.com/news/rss.xml"},
    {"c": "IT", "name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index"},
    {"c": "IT", "name": "ScienceDaily 기술", "url": "https://www.sciencedaily.com/rss/top/technology.xml"},
    {"c": "과학", "name": "Quanta Magazine", "url": "https://www.quantamagazine.org/feed/"},
    {"c": "과학", "name": "Phys.org", "url": "https://phys.org/rss-feed/"},
    {"c": "과학", "name": "ScienceDaily 과학", "url": "https://www.sciencedaily.com/rss/top/science.xml"},
    {"c": "과학", "name": "NASA", "url": "https://www.nasa.gov/feed/"},
    {"c": "역사", "name": "Smithsonian Magazine", "url": "https://www.smithsonianmag.com/rss/latest_articles/"},
    {"c": "미스터리", "name": "Atlas Obscura", "url": "https://www.atlasobscura.com/feeds/latest"},
]


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


def http_get(url, timeout=20, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET 실패 {url}: {last}")


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def make_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


# ---------- 위키백과 ----------
def wiki_search(host, query, limit=30):
    qs = urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": limit, "srnamespace": 0, "format": "json",
    })
    data = json.loads(http_get(f"https://{host}/w/api.php?" + qs))
    return [x["title"] for x in data.get("query", {}).get("search", [])]


def wiki_summary(host, title):
    url = f"https://{host}/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"), safe="")
    d = json.loads(http_get(url))
    if d.get("type") != "standard":
        return None
    extract = (d.get("extract") or "").strip()
    page = (d.get("content_urls") or {}).get("desktop", {}).get("page")
    if len(extract) < 80 or not page:
        return None
    return {"title": d.get("title") or title, "text": extract, "url": page, "desc": d.get("description") or ""}


# ---------- RSS ----------
def parse_rss(xml_text):
    out = []
    root = ET.fromstring(xml_text)
    for it in root.iter("item"):
        title = strip_tags(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        desc = strip_tags(it.findtext("description"))
        pub = (it.findtext("pubDate") or "").strip()
        if title and link.startswith("http") and len(desc) > 60:
            out.append({"title": title, "url": link, "text": desc, "pub": pub})
    return out


def rss_date(pub):
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(pub, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


# ---------- 요약 ----------
def split_sentences(text):
    parts = re.split(r"(?<=[.!?다])\s+", text.strip())
    return [p for p in parts if p]


def fallback_summary(text):
    s = split_sentences(text)
    b = " ".join(s[:2])[:140]
    more = " ".join(s[2:4])[:220]
    return {"t": "", "b": b, "more": more}


def ai_summary(title, text, cat):
    """가져온 텍스트 안의 내용만 사용. 부적합하면 None."""
    if not API_KEY:
        return fallback_summary(text)
    prompt = f"""아래 '원문'만 근거로 한국어 읽을거리 카드를 만들어줘.
카테고리: {cat}
제목: {title}

규칙:
- 원문에 없는 내용은 절대 추가하지 마. 모르면 쓰지 마.
- 말투는 반말 서술체(~야, ~임, ~함).
- b: 2문장 이내, 110자 안쪽. 가장 흥미로운 핵심만.
- more: 2~3문장, 200자 안쪽. b에 없는 추가 내용.
- 잔혹한 묘사, 피해자 신상, 선정적 표현은 빼.
- 원문이 너무 빈약하거나 목록/동음이의 문서처럼 읽을거리가 안 되면 {{"skip":true}} 만 출력.
- 영어 원문이면 한국어로 옮겨서 써.
- t: 제목. 영어 제목이면 자연스러운 한국어 제목(25자 이내)으로, 한국어면 그대로.
오직 JSON 한 개만 출력: {{"t":"...","b":"...","more":"..."}}

원문:
{text[:2500]}"""
    body = json.dumps({
        "model": MODEL, "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8"))
        txt = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
        d = json.loads(txt)
    except Exception as e:  # noqa
        print("  AI 요약 실패:", e)
        return None
    if d.get("skip") or not d.get("b"):
        return None
    return {"t": str(d.get("t", ""))[:60], "b": str(d["b"])[:160], "more": str(d.get("more", ""))[:260]}


# ---------- 메인 ----------
def load_items():
    try:
        with open(DATA, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except FileNotFoundError:
        return []


def collect_wiki(existing_urls, existing_titles):
    new = []
    for src in WIKI_SOURCES:
        if src["lang"] != "ko" and not API_KEY:
            print(f"{src['name']}: 번역에 ANTHROPIC_API_KEY 가 필요해서 건너뜀")
            continue
        print(f"== {src['name']}")
        for cat, queries in src["queries"].items():
            got = 0
            qs = queries[:]
            random.shuffle(qs)
            for q in qs:
                if got >= PER_CAT:
                    break
                try:
                    titles = wiki_search(src["host"], q)
                except Exception as e:  # noqa
                    print("검색 실패", q, e)
                    continue
                random.shuffle(titles)
                for t in titles:
                    if got >= PER_CAT:
                        break
                    try:
                        s = wiki_summary(src["host"], t)
                    except Exception as e:  # noqa
                        print("요약 실패", t, e)
                        continue
                    if not s or s["url"] in existing_urls or s["title"] in existing_titles:
                        continue
                    if cat == "인물" and not person_ok(s["desc"], s["text"], src["lang"]):
                        continue
                    card = ai_summary(s["title"], s["text"], cat)
                    if not card:
                        continue
                    item = {
                        "id": make_id(s["url"]), "c": cat, "t": card.get("t") or s["title"],
                        "b": card["b"], "more": card["more"],
                        "src": src["name"], "url": s["url"],
                        "date": datetime.now(timezone.utc).date().isoformat(), "k": "wiki",
                    }
                    new.append(item)
                    existing_urls.add(s["url"])
                    existing_titles.add(s["title"])
                    got += 1
                    print(f"  + [{cat}] {s['title']}")
                    time.sleep(0.5)
    return new


def collect_rss(existing_urls):
    new = []
    if not API_KEY:
        print("RSS는 AI 요약(한국어 번역)이 필요해서 ANTHROPIC_API_KEY 없으면 건너뜀")
        return new
    for feed in RSS_FEEDS:
        try:
            entries = parse_rss(http_get(feed["url"]))
        except Exception as e:  # noqa
            print("RSS 실패", feed["name"], e)
            continue
        random.shuffle(entries)
        got = 0
        for e in entries:
            if got >= PER_FEED:
                break
            if e["url"] in existing_urls:
                continue
            card = ai_summary(e["title"], e["text"], feed["c"])
            if not card:
                continue
            new.append({
                "id": make_id(e["url"]), "c": feed["c"], "t": card.get("t") or e["title"][:80],
                "b": card["b"], "more": card["more"], "src": feed["name"], "url": e["url"],
                "date": rss_date(e["pub"]) or datetime.now(timezone.utc).date().isoformat(), "k": "rss",
            })
            existing_urls.add(e["url"])
            got += 1
            print(f"  + [{feed['c']}] {e['title'][:40]}")
    return new


def main():
    items = load_items()
    urls = {i.get("url") for i in items if i.get("url")}
    titles = {i.get("t") for i in items}
    print(f"기존 {len(items)}개")
    new = collect_wiki(urls, titles) + collect_rss(urls)
    print(f"새로 {len(new)}개")
    if DRY:
        print(json.dumps(new, ensure_ascii=False, indent=1))
        return
    items = (items + new)[-MAX_ITEMS:]
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
