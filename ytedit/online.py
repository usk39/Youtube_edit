"""ネット上から素材(画像・背景・BGM・効果音)を自動で取ってくる。

対応サイト(API キーが無いサイトは自動でスキップ):
  画像  : Pixabay(キー要・日本語検索可) / Pexels(キー要・日本語検索可) / Openverse(キー不要)
  効果音: Freesound(キー要) / Openverse(キー不要)
  BGM   : Jamendo(クライアントID要) / Openverse(キー不要)

- 商用利用OK・改変OK のライセンスだけを使う(YouTube の収益化を想定)。CC BY などクレジット表記が
  必要な素材は、使った分だけ credits.txt と概要欄に自動で書き出す。
- 一度取った素材は assets/_online にキャッシュし、同じ検索では再取得しない。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "ytedit/0.2 (YouTube editing automation)"

# ------------------------------------------------------------------ 検索語
SE_QUERIES = {
    "surprise": ["surprise sound effect", "cartoon surprise"],
    "point": ["ding chime", "bell ding"],
    "question": ["question cartoon", "boing"],
    "shock": ["impact hit", "dramatic hit"],
    "laugh": ["cartoon laugh", "comedy jingle"],
    "transition": ["whoosh", "swoosh transition"],
    "cutin": ["swoosh impact", "whoosh hit"],
    "popup": ["pop notification", "bubble pop"],
}
# シーンの雰囲気によって選ぶ効果音を変える (種類, 雰囲気) → 検索語
SE_MOOD_QUERIES = {
    ("surprise", "tense"): ["dramatic sting", "suspense hit"],
    ("surprise", "comical"): ["cartoon boing", "comedy surprise"],
    ("shock", "tense"): ["dramatic boom", "cinematic impact"],
    ("shock", "comical"): ["comedy fail", "cartoon slip"],
    ("point", "tense"): ["suspense stinger"],
    ("transition", "tense"): ["riser whoosh", "dark whoosh"],
    ("transition", "comical"): ["cartoon whoosh", "slide whistle"],
    ("transition", "sad"): ["soft whoosh", "chime soft"],
    ("question", "comical"): ["cartoon question", "boing"],
}
BGM_QUERIES = {
    "calm": ["calm piano", "lofi chill"],
    "bright": ["happy upbeat", "cheerful ukulele"],
    "tense": ["suspense", "tension cinematic"],
    "sad": ["sad piano", "melancholy"],
    "comical": ["funny comedy", "quirky playful"],
}
BACKGROUND_FALLBACK_EN = ["city skyline", "abstract blue background", "office"]

# Claude 解析が無いときに使う、ニュース頻出語の英訳(英語でしか検索できないサイト用)
JP_EN = {
    "経済": "economy", "株価": "stock market", "株": "stocks", "日経平均": "stock market chart", "円安": "japanese yen",
    "円高": "japanese yen", "為替": "currency exchange", "物価": "prices supermarket", "値上げ": "price increase",
    "インフレ": "inflation", "金利": "interest rate", "利上げ": "interest rate", "日銀": "bank of japan", "銀行": "bank",
    "税金": "tax", "増税": "tax", "減税": "tax cut", "消費税": "consumption tax", "給料": "salary", "賃金": "wages",
    "年金": "pension", "景気": "economy", "不景気": "recession", "企業": "company office", "倒産": "bankruptcy",
    "政治": "politics", "国会": "japan parliament", "首相": "prime minister", "総理": "prime minister", "政府": "government",
    "選挙": "election", "投票": "voting", "政党": "politics", "大臣": "minister", "外交": "diplomacy", "首脳": "summit",
    "戦争": "war", "軍事": "military", "防衛": "defense", "ミサイル": "missile", "中国": "china", "アメリカ": "usa",
    "米国": "usa", "韓国": "south korea", "ロシア": "russia", "ウクライナ": "ukraine", "北朝鮮": "north korea",
    "台湾": "taiwan", "日本": "japan", "東京": "tokyo", "大阪": "osaka", "福岡": "fukuoka", "博多": "fukuoka",
    "天気": "weather", "台風": "typhoon", "地震": "earthquake", "津波": "tsunami", "大雨": "heavy rain", "災害": "disaster",
    "猛暑": "heat wave", "気温": "thermometer", "雪": "snow", "火事": "fire", "事故": "accident", "事件": "police",
    "警察": "police", "逮捕": "arrest", "裁判": "court", "犯罪": "crime", "詐欺": "scam", "医療": "medical",
    "病院": "hospital", "感染": "virus", "ワクチン": "vaccine", "薬": "medicine", "健康": "health", "高齢者": "elderly",
    "少子化": "birth rate", "子育て": "parenting", "教育": "education", "学校": "school", "大学": "university",
    "受験": "exam", "就職": "job interview", "仕事": "work", "働き方": "office work", "残業": "overtime work",
    "AI": "artificial intelligence", "人工知能": "artificial intelligence", "スマホ": "smartphone", "SNS": "social media",
    "ネット": "internet", "テクノロジー": "technology", "半導体": "semiconductor", "電気": "electricity",
    "電気代": "electricity bill", "ガソリン": "gasoline", "エネルギー": "energy", "原発": "nuclear power plant",
    "環境": "environment", "温暖化": "global warming", "米": "rice", "お米": "rice", "食品": "food", "野菜": "vegetables",
    "農業": "agriculture", "観光": "tourism", "旅行": "travel", "インバウンド": "tourists", "外国人": "tourists",
    "スポーツ": "sports", "野球": "baseball", "サッカー": "soccer", "オリンピック": "olympics", "芸能": "celebrity",
    "住宅": "house", "家賃": "apartment", "不動産": "real estate", "車": "car", "電車": "train", "鉄道": "train",
    "飛行機": "airplane", "空港": "airport", "宇宙": "space", "ロケット": "rocket", "貿易": "trade port",
    "関税": "tariff trade", "輸出": "export container", "人口": "crowd", "結婚": "wedding", "お金": "money",
}

LICENSE_NAMES = {"cc0": "CC0", "pdm": "Public Domain", "by": "CC BY", "by-sa": "CC BY-SA"}


def to_english(word: str) -> str | None:
    if re.fullmatch(r"[A-Za-z0-9 \-]+", word):
        return word
    if word in JP_EN:
        return JP_EN[word]
    for jp, en in sorted(JP_EN.items(), key=lambda x: -len(x[0])):  # 「円安進行」→ 円安
        if len(jp) >= 2 and jp in word:
            return en
    return None


# ------------------------------------------------------------------ HTTP
def http_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def http_download(url: str, out: Path, headers: dict | None = None) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if len(data) < 1000:
        raise ValueError("ファイルが小さすぎます")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def _ext(url: str, default: str) -> str:
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    return ext if ext in {".jpg", ".jpeg", ".png", ".webp", ".mp3", ".ogg", ".wav", ".flac", ".m4a"} else default


def _cc_code(license_url: str) -> str | None:
    """CC ライセンス URL → コード。商用/改変不可(nc/nd)や sampling+ は None。"""
    u = (license_url or "").lower()
    if "publicdomain/zero" in u:
        return "cc0"
    if "publicdomain/mark" in u:
        return "pdm"
    m = re.search(r"/licenses/([a-z\-]+)/", u)
    if not m or "nc" in m[1].split("-") or "nd" in m[1].split("-") or "sampling" in m[1]:
        return None
    return m[1]


# ------------------------------------------------------------------ 各サイト
# 戻り値は候補のリスト: {"url", "title", "creator", "license", "license_url", "page", "provider", "duration"}

def search_pixabay_images(query: str, key: str, n: int = 8) -> list[dict]:
    q = urllib.parse.urlencode({"key": key, "q": query[:100], "lang": "ja", "image_type": "photo",
                                "orientation": "horizontal", "safesearch": "true", "per_page": max(3, n)})
    hits = http_json(f"https://pixabay.com/api/?{q}").get("hits", [])
    return [{"url": h.get("largeImageURL") or h["webformatURL"], "title": h.get("tags", ""), "creator": h.get("user", ""),
             "license": "Pixabay License", "license_url": "https://pixabay.com/service/license-summary/",
             "page": h.get("pageURL", ""), "provider": "pixabay", "needs_credit": False} for h in hits]


def search_pexels_images(query: str, key: str, n: int = 8) -> list[dict]:
    q = urllib.parse.urlencode({"query": query, "per_page": n, "orientation": "landscape", "locale": "ja-JP"})
    photos = http_json(f"https://api.pexels.com/v1/search?{q}", {"Authorization": key}).get("photos", [])
    return [{"url": p["src"].get("large2x") or p["src"]["large"], "title": p.get("alt", ""),
             "creator": p.get("photographer", ""), "license": "Pexels License", "license_url": "https://www.pexels.com/license/",
             "page": p.get("url", ""), "provider": "pexels", "needs_credit": False} for p in photos]


def _openverse(kind: str, query: str, n: int, extra: dict, allowed: set[str]) -> list[dict]:
    q = urllib.parse.urlencode({"q": query, "page_size": n, "license_type": "commercial,modification", **extra})
    results = http_json(f"https://api.openverse.org/v1/{kind}/?{q}").get("results", [])
    out = []
    for r in results:
        lic = (r.get("license") or "").lower()
        if lic not in allowed or not r.get("url"):
            continue
        out.append({"url": r["url"], "title": r.get("title") or "", "creator": r.get("creator") or "",
                    "license": LICENSE_NAMES.get(lic, lic.upper()) + (f" {r['license_version']}" if r.get("license_version") else ""),
                    "license_url": r.get("license_url") or "", "page": r.get("foreign_landing_url") or "",
                    "provider": f"openverse/{r.get('source') or r.get('provider')}",
                    "duration": (r.get("duration") or 0) / 1000.0, "needs_credit": lic not in ("cc0", "pdm"),
                    "attribution": r.get("attribution") or ""})
    return out


def search_openverse_images(query: str, n: int, allowed: set[str]) -> list[dict]:
    return _openverse("images", query, n, {"aspect_ratio": "wide", "size": "large,medium", "mature": "false"}, allowed)


def search_openverse_audio(query: str, n: int, allowed: set[str], category: str) -> list[dict]:
    return _openverse("audio", query, n, {"category": category, "mature": "false"}, allowed)


def search_freesound(query: str, key: str, n: int, allowed: set[str], max_duration: float = 4.0) -> list[dict]:
    q = urllib.parse.urlencode({"query": query, "token": key, "page_size": n, "sort": "rating_desc",
                                "filter": f"duration:[0.1 TO {max_duration}]",
                                "fields": "id,name,username,license,previews,duration,url"})
    out = []
    for r in http_json(f"https://freesound.org/apiv2/search/text/?{q}").get("results", []):
        code = _cc_code(r.get("license", ""))
        url = (r.get("previews") or {}).get("preview-hq-mp3")
        if code in allowed and url:
            out.append({"url": url, "title": r.get("name", ""), "creator": r.get("username", ""),
                        "license": LICENSE_NAMES.get(code, code), "license_url": r.get("license", ""),
                        "page": r.get("url", ""), "provider": "freesound", "duration": r.get("duration", 0),
                        "needs_credit": code not in ("cc0", "pdm")})
    return out


def search_jamendo(query: str, client_id: str, n: int, allowed: set[str]) -> list[dict]:
    q = urllib.parse.urlencode({"client_id": client_id, "format": "json", "limit": n, "fuzzytags": query.replace(" ", "+"),
                                "audioformat": "mp32", "vocalinstrumental": "instrumental", "order": "popularity_total",
                                "include": "licenses"})
    out = []
    for r in http_json(f"https://api.jamendo.com/v3.0/tracks/?{q}").get("results", []):
        code = _cc_code(r.get("license_ccurl", ""))
        url = r.get("audiodownload") if r.get("audiodownload_allowed") else None
        url = url or r.get("audio")
        if code in allowed and url:
            out.append({"url": url, "title": r.get("name", ""), "creator": r.get("artist_name", ""),
                        "license": LICENSE_NAMES.get(code, code), "license_url": r.get("license_ccurl", ""),
                        "page": r.get("shareurl", ""), "provider": "jamendo", "duration": float(r.get("duration") or 0),
                        "needs_credit": code not in ("cc0", "pdm")})
    return out


# ------------------------------------------------------------------ まとめ役
class OnlineSource:
    def __init__(self, cfg: dict):
        oc = cfg["online"]
        self.enabled = bool(oc.get("enabled", True))
        self.cache = Path(oc.get("cache_dir") or Path(cfg["assets_dir"]) / "_online")
        self.max_downloads = int(oc.get("max_downloads", 80))
        self.allowed = set(oc.get("allowed_licenses", ["cc0", "pdm", "by"]))
        self.keys = {k: oc.get(k) or os.environ.get(k.upper()) for k in
                     ("pixabay_api_key", "pexels_api_key", "freesound_api_key", "jamendo_client_id")}
        if cfg.get("pexels_api_key") and not self.keys["pexels_api_key"]:  # 旧設定の互換
            self.keys["pexels_api_key"] = cfg["pexels_api_key"]
        self.downloads = 0
        self.used: set[str] = set()
        self.failed_providers: set[str] = set()
        self._qcache_path = self.cache / "queries.json"
        try:
            self._qcache = json.loads(self._qcache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._qcache = {}

    # ---------------------------------------------------- 共通処理
    def _search(self, key: str, fn) -> list[dict]:
        if key in self._qcache:
            return self._qcache[key]
        try:
            results = fn()
        except Exception as e:
            provider = key.split(":")[0].split("-")[0]
            print(f"[ネット素材] {provider} の検索に失敗: {e}")
            self.failed_providers.add(provider)
            return []
        self._qcache[key] = results
        self.cache.mkdir(parents=True, exist_ok=True)
        self._qcache_path.write_text(json.dumps(self._qcache, ensure_ascii=False, indent=1), encoding="utf-8")
        return results

    def _fetch(self, cand: dict, sub: str, default_ext: str) -> Path | None:
        name = hashlib.md5(cand["url"].encode()).hexdigest()[:16] + _ext(cand["url"], default_ext)
        path = self.cache / sub / name
        meta = path.with_name(path.name + ".json")
        if not path.exists():
            if self.downloads >= self.max_downloads:
                return None
            try:
                http_download(cand["url"], path)
                self.downloads += 1
            except Exception as e:
                print(f"[ネット素材] ダウンロード失敗 ({cand['provider']}): {e}")
                return None
            meta.write_text(json.dumps(cand, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def _pick(self, candidates: list[dict], sub: str, ext: str, avoid_used: bool = True) -> tuple[Path, dict] | None:
        ordered = [c for c in candidates if c["url"] not in self.used] if avoid_used else []
        ordered += [c for c in candidates if c not in ordered]
        for cand in ordered[:5]:
            p = self._fetch(cand, sub, ext)
            if p:
                self.used.add(cand["url"])
                return p, cand
        return None

    def _alive(self, provider: str, key_name: str | None = None) -> bool:
        if provider in self.failed_providers:
            return False
        return key_name is None or bool(self.keys.get(key_name))

    # ---------------------------------------------------- 画像
    def image(self, jp_words: list[str], en_queries: list[str], sub: str = "images") -> tuple[Path, dict] | None:
        if not self.enabled:
            return None
        en = [q for q in en_queries if q] + [e for e in (to_english(w) for w in jp_words) if e]
        attempts = []
        if self._alive("pixabay", "pixabay_api_key"):
            attempts += [(f"pixabay:{w}", lambda w=w: search_pixabay_images(w, self.keys["pixabay_api_key"])) for w in jp_words[:2]]
        if self._alive("pexels", "pexels_api_key"):
            attempts += [(f"pexels:{w}", lambda w=w: search_pexels_images(w, self.keys["pexels_api_key"]))
                         for w in (en[:1] + jp_words[:1])]
        if self._alive("openverse"):
            attempts += [(f"openverse-img:{q}", lambda q=q: search_openverse_images(q, 12, self.allowed)) for q in en[:2]]
        for key, fn in attempts:
            if not self._alive(key.split(":")[0].split("-")[0]):
                continue
            hit = self._pick(self._search(key, fn), sub, ".jpg")
            if hit:
                return hit
        return None

    # ---------------------------------------------------- 音
    def se(self, kind: str, variant: int = 0, mood: str | None = None) -> tuple[Path, dict] | None:
        if not self.enabled:
            return None
        queries = SE_MOOD_QUERIES.get((kind, mood), []) + SE_QUERIES.get(kind, [kind])
        for q in queries:
            cands = []
            if self._alive("freesound", "freesound_api_key"):
                cands = self._search(f"freesound:{q}", lambda q=q: search_freesound(q, self.keys["freesound_api_key"], 10, self.allowed))
            if not cands and self._alive("openverse"):
                cands = [c for c in self._search(f"openverse-se:{q}",
                                                 lambda q=q: search_openverse_audio(q, 15, self.allowed, "sound_effect"))
                         if 0 < c.get("duration", 0) <= 5]
            if cands:
                # 種類ごとに 2〜3 個を使い回してバリエーションを出す
                cand = cands[variant % min(3, len(cands))]
                hit = self._pick([cand] + cands, f"se/{kind}", ".mp3", avoid_used=False)
                if hit:
                    return hit
        return None

    def bgm(self, mood: str) -> tuple[Path, dict] | None:
        if not self.enabled:
            return None
        for q in BGM_QUERIES.get(mood, [mood]):
            cands = []
            if self._alive("jamendo", "jamendo_client_id"):
                cands = self._search(f"jamendo:{q}", lambda q=q: search_jamendo(q, self.keys["jamendo_client_id"], 10, self.allowed))
            if not cands and self._alive("openverse"):
                cands = [c for c in self._search(f"openverse-bgm:{q}",
                                                 lambda q=q: search_openverse_audio(q, 15, self.allowed, "music"))
                         if c.get("duration", 0) >= 60]
            hit = self._pick(cands, f"bgm/{mood}", ".mp3")
            if hit:
                return hit
        return None


def meta_for(path: str | Path) -> dict | None:
    """ダウンロード済み素材のライセンス情報(無ければ None = 手持ち素材)。"""
    m = Path(str(path) + ".json")
    if m.exists():
        try:
            return json.loads(m.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None
