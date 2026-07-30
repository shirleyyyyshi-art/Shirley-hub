#!/usr/bin/env python3
"""Fetch real daily content for the English News / MOM Policy pages.
Pure standard library, no pip installs needed so the GitHub Action stays simple.
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

UA = "Mozilla/5.0 (compatible; ShirleyAppDailyFetch/1.0)"

COMMON_WORDS = set("""
a about above after again against all am an and any are aren't as at be because been
before being below between both but by can't cannot could couldn't did didn't do does
doesn't doing don't down during each few for from further had hadn't has hasn't have
haven't having he he'd he'll he's her here here's hers herself him himself his how
how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most
mustn't my myself no nor not of off on once only or other ought our ours ourselves out
over own same shan't she she'd she'll she's should shouldn't so some such than that
that's the their theirs them themselves then there there's these they they'd they'll
they're they've this those through to too under until up very was wasn't we we'd
we'll we're we've were weren't what what's when when's where where's which while who
who's whom why why's with won't would wouldn't you you'd you'll you're you've your
yours yourself yourselves
new says say said also will one two three first last year years time day days week
weeks month months people man woman government minister company companies country
city singapore world would could like get gets got make made many much more most
plan plans work works working worker workers home house public private business
market markets price prices high low still even after before since around near far
help helps needed need needs including according report reports found find finds
group groups team teams part parts point points case cases number numbers rate rates
level levels change changes issue issues area areas move moves moved
""".split())

SOURCES = {
    "economist": "https://www.economist.com/finance-and-economics/rss.xml",
    "st": "https://www.straitstimes.com/news/business/rss.xml",
    "cna": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
}

MOM_LISTING = "https://www.mom.gov.sg/newsroom/press-releases"
MOM_BASE = "https://www.mom.gov.sg"

# Skip items that touch on distressing topics -- this is a personal learning app,
# so we scan past the first item for something more appropriate to study English from.
SENSITIVE_KEYWORDS = [
    "crime", "criminal", "court", "courts", "charged", "arrest", "jail", "prison",
    "murder", "kill", "killed", "killing", "dead", "death", "died", "dies", "suicide",
    "assault", "abuse", "rape", "molest", "terror", "terrorist", "bomb", "shooting",
    "shot", "stab", "stabbing", "drug", "narcotics", "cannabis", "trafficking",
    "war", "attack", "victim", "hostage", "gaza", "conflict", "riot", "gun",
]


def is_sensitive(text):
    low = text.lower()
    return any(kw in low for kw in SENSITIVE_KEYWORDS)


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&mdash;", "—")
    s = s.replace("&lsquo;", "'").replace("&rsquo;", "'").replace("&ldquo;", '"').replace("&rdquo;", '"')
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_rss_first_clean_item(xml_bytes, scan_limit=15):
    root = ElementTree.fromstring(xml_bytes)
    items = root.findall(".//item")[:scan_limit]
    fallback = None
    for item in items:
        title = strip_html((item.findtext("title") or "").strip())
        desc = strip_html((item.findtext("description") or "").strip())
        link = (item.findtext("link") or "").strip()
        if not title:
            continue
        candidate = {"headline": title, "teaser": desc, "url": link}
        if fallback is None:
            fallback = candidate
        if not is_sensitive(title + " " + desc):
            return candidate
    return fallback


def lookup_definition(word):
    try:
        raw = fetch(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=8)
        data = json.loads(raw)
        entry = data[0]
        phonetic = entry.get("phonetic", "")
        for meaning in entry.get("meanings", []):
            for d in meaning.get("definitions", []):
                if d.get("definition"):
                    return {"word": word, "phonetic": phonetic, "def": d["definition"]}
    except Exception:
        return None
    return None


def pick_vocab(text, max_words=2):
    words = re.findall(r"[A-Za-z']+", text)
    seen = set()
    candidates = []
    for w in words:
        lw = w.lower()
        if len(lw) >= 7 and lw not in COMMON_WORDS and lw not in seen:
            seen.add(lw)
            candidates.append(lw)
    out = []
    for w in candidates:
        d = lookup_definition(w)
        if d:
            out.append(d)
        if len(out) >= max_words:
            break
        time.sleep(0.3)
    return out


def get_rss_content(key, url):
    try:
        item = parse_rss_first_clean_item(fetch(url))
        if not item or not item["headline"]:
            return None
        if not item["teaser"]:
            item["teaser"] = item["headline"]
        return item
    except Exception as e:
        print(f"[warn] failed to fetch {key}: {e}")
        return None


def get_mom_content():
    try:
        html = fetch(MOM_LISTING).decode("utf-8", errors="ignore")
        m = re.search(r'<a[^>]*href="(/newsroom/press-releases/[^"]+)"[^>]*>(.*?)</a>', html, re.S)
        if not m:
            return None
        href, title_html = m.group(1), m.group(2)
        headline = strip_html(title_html)
        url = MOM_BASE + href
        teaser = ""
        try:
            detail_html = fetch(url).decode("utf-8", errors="ignore")
            # The real article body lives inside a "...documentcontent..." wrapper div;
            # the rest of the page is navigation/eservices chrome we don't want to scrape.
            body_match = re.search(r'id="[^"]*documentcontent[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', detail_html, re.S)
            body_html = body_match.group(1) if body_match else detail_html
            paras = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)
            for p in paras:
                clean = strip_html(p)
                if len(clean) > 60:
                    teaser = clean[:320]
                    break
        except Exception as e:
            print(f"[warn] failed to fetch MOM detail page: {e}")
        return {"headline": headline, "teaser": teaser or headline, "url": url}
    except Exception as e:
        print(f"[warn] failed to fetch MOM listing: {e}")
        return None


def gemini_prompt(econ_seed):
    econ_line = ""
    if econ_seed:
        econ_line = ('\n\nA real Economist headline from today, use it as the inspiration/topic for "economist_article" below '
                     '(do not just repeat the headline, write a genuine ~5-paragraph article exploring the topic): '
                     '"' + econ_seed.get("headline", "") + '" — ' + econ_seed.get("teaser", ""))
    return """Generate fresh English-learning material for a Singapore-based learner. Reply with ONLY raw JSON, no markdown fences, matching exactly this shape:
{
  "life_vocab": [ {"en": "word or short phrase", "cn": "Chinese translation", "def": "simple English definition", "ex": "one example sentence", "emoji": "one relevant emoji"} ... 10 items, everyday life topic (pick a fresh theme each time, e.g. supermarket, gym, clinic, hawker centre, MRT, weather, cooking) ],
  "level_vocab": [ {"w": "word", "ipa": "IPA in slashes", "pos": "part of speech abbreviation e.g. adj./v./n.", "cn": "Chinese translation", "def": "simple English definition", "ex": "one example sentence"} ... 10 intermediate/upper-intermediate professional-English words, different from common ones like articulate/leverage/mitigate/ambiguous/proactive/candid/viable/reluctant/consolidate/discrepancy/streamline/redundant/tentative/escalate/feasible/forthcoming/meticulous/pragmatic/scrutinise/unprecedented/cohesive/deploy/expedite/holistic/incentivise/nuanced/onboard/resilient/substantiate/versatile ],
  "listening": {
    "source": "BBC Learning English style · Intermediate  (or Upper-Intermediate, or 'CNA style · Intermediate' etc, vary it)",
    "title": "short title for a Singapore-relevant news-style topic",
    "transcript": "3-4 sentence short passage, Singapore or Asia relevant, natural spoken style",
    "vocab_words": [ {"word": "a word appearing verbatim in the transcript", "def": "IPA + part of speech + English definition + Chinese translation combined in one string, e.g. '/wɜːd/ (n.) short meaning — 中文翻译'"} ... 2 to 3 items ]
  },
  "economist_article": {
    "title": "article title",
    "paras": ["paragraph 1", "paragraph 2", "paragraph 3", "paragraph 4", "paragraph 5"],
    "cn": "a full Chinese translation of the whole article, as one string",
    "vocab": [ {"w": "word appearing in the article", "ipa": "IPA in slashes", "pos": "adj./v./n. etc", "mean": "Chinese meaning", "def": "English definition", "ex": "example sentence"} ... 10 items, genuinely advanced/business vocabulary drawn from the article text ],
    "gems": [ {"s": "one genuinely well-constructed sentence copied verbatim from the article", "why": "one sentence in English explaining the rhetorical technique, then the same explanation in Chinese"} ... 1 to 2 items ]
  }
}""" + econ_line + """
Make it genuinely different from a typical example, vary the topic each time. Output nothing except the JSON object."""


def call_gemini(prompt):
    if not GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def build_listening_html(listening):
    transcript = listening.get("transcript", "")
    for vw in listening.get("vocab_words", []):
        word = vw.get("word", "")
        definition = vw.get("def", "")
        if not word:
            continue
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        span = '<span class="dict-word" data-action="lookup-word" data-def="' + definition.replace('"', "&quot;") + '">' + word + '</span>'
        transcript, n = pattern.subn(span, transcript, count=1)
    return {
        "source": listening.get("source", ""),
        "title": listening.get("title", ""),
        "transcript": transcript,
    }


def get_ai_content(econ_seed):
    if not GEMINI_API_KEY:
        print("[info] GEMINI_API_KEY not set, skipping AI-generated vocab/listening/article (local pools will be used instead)")
        return None
    try:
        data = call_gemini(gemini_prompt(econ_seed))
        out = {}
        if data.get("life_vocab"):
            out["lifeVocab"] = data["life_vocab"]
        if data.get("level_vocab"):
            out["levelVocab"] = data["level_vocab"]
        if data.get("listening"):
            out["listening"] = build_listening_html(data["listening"])
        if data.get("economist_article"):
            out["economistArticle"] = data["economist_article"]
        return out or None
    except Exception as e:
        print(f"[warn] Gemini generation failed: {e}")
        return None


def main():
    sgt_now = datetime.now(timezone.utc) + timedelta(hours=8)
    result = {
        "date": sgt_now.strftime("%Y-%m-%d"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }

    econ = get_rss_content("economist", SOURCES["economist"])
    if econ:
        econ["vocab"] = pick_vocab(econ["headline"] + " " + econ["teaser"])
        result["economist"] = econ

    st = get_rss_content("st", SOURCES["st"])
    if st:
        result["st"] = st

    cna = get_rss_content("cna", SOURCES["cna"])
    if cna:
        result["cna"] = cna

    mom = get_mom_content()
    if mom:
        result["mom"] = mom

    ai = get_ai_content(econ)
    if ai:
        result.update(ai)

    with open("data/daily.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
