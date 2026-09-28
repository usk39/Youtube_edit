"""素材フォルダの管理とキーワード検索。

assets/
  bgm/<mood>/*.mp3         mood = calm / bright / tense (フォルダ名が雰囲気)
  se/<kind>/*.wav          kind = surprise / laugh / point / question / shock / transition / cutin / popup
  materials/*.png          ファイル名がタグ (例: 日銀_金利_グラフ.png)。tags.yaml で追加タグも可
  backgrounds/*.png        同上
  characters/<id>/<表情>.png   id = sumire / aoi, 表情 = normal smile laugh surprised angry sad thinking doya jito
  characters/<id>/face/<表情>.png  (任意) 丸ワイプ用の顔画像。無ければ立ち絵の上部を自動で切り抜く
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}

# 表情が無いときの代わり
EXPRESSION_FALLBACK = {
    "laugh": ["smile"], "smile": ["normal"], "surprised": ["normal"], "angry": ["jito", "normal"],
    "sad": ["normal"], "thinking": ["normal"], "doya": ["smile", "normal"], "jito": ["angry", "normal"],
}


def _tags_from_name(path: Path) -> list[str]:
    return [t for t in re.split(r"[_\-\s・,、]+", path.stem.lower()) if t]


class AssetLibrary:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.materials = self._scan_images("materials")
        self.backgrounds = self._scan_images("backgrounds")

    # --------------------------------------------------------- 画像(タグ付き)
    def _scan_images(self, sub: str) -> list[tuple[Path, list[str]]]:
        d = self.root / sub
        if not d.exists():
            return []
        extra: dict[str, list[str]] = {}
        tags_file = d / "tags.yaml"
        if tags_file.exists():
            extra = yaml.safe_load(tags_file.read_text(encoding="utf-8")) or {}
        items = []
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in IMAGE_EXT:
                tags = _tags_from_name(p) + [str(t).lower() for t in extra.get(p.name, [])]
                tags += [q.name.lower() for q in p.relative_to(d).parents if q.name]
                items.append((p, tags))
        return items

    def material_tags(self) -> list[str]:
        return [t for _, tags in self.materials for t in tags]

    def background_tags(self) -> list[str]:
        return [t for _, tags in self.backgrounds for t in tags]

    @staticmethod
    def _match(items: list[tuple[Path, list[str]]], keywords: list[str]) -> Path | None:
        best, best_score = None, 0.0
        for path, tags in items:
            score = 0.0
            for rank, kw in enumerate(keywords):
                kw = kw.lower()
                weight = 1.0 / (1 + rank * 0.3)
                for t in tags:
                    if kw == t:
                        score += 3 * weight
                    elif len(t) >= 2 and len(kw) >= 2 and (t in kw or kw in t):
                        score += 1 * weight
            if score > best_score:
                best, best_score = path, score
        return best

    def find_material(self, keywords: list[str]) -> Path | None:
        return self._match(self.materials, keywords)

    def find_background(self, keywords: list[str]) -> Path | None:
        return self._match(self.backgrounds, keywords) if keywords else None

    def default_background(self) -> Path | None:
        for path, tags in self.backgrounds:
            if "default" in tags or "デフォルト" in tags:
                return path
        return self.backgrounds[0][0] if self.backgrounds else None

    # --------------------------------------------------------- 音
    def _audio_in(self, sub: str) -> list[Path]:
        d = self.root / sub
        return sorted(p for p in d.rglob("*") if p.suffix.lower() in AUDIO_EXT) if d.exists() else []

    def bgm(self, mood: str) -> Path | None:
        files = self._audio_in(f"bgm/{mood}") or self._audio_in("bgm")
        return files[0] if files else None

    def bgm_list(self, mood: str) -> list[Path]:
        return self._audio_in(f"bgm/{mood}") or self._audio_in("bgm")

    def se(self, kind: str, seed: int = 0) -> Path | None:
        files = self._audio_in(f"se/{kind}")
        return files[seed % len(files)] if files else None

    # --------------------------------------------------------- キャラクター
    def character(self, char_id: str, expression: str) -> Path | None:
        return self._char_file(self.root / "characters" / char_id, expression)

    def character_face(self, char_id: str, expression: str) -> Path | None:
        return self._char_file(self.root / "characters" / char_id / "face", expression)

    def expressions(self, char_id: str) -> list[str]:
        d = self.root / "characters" / char_id
        return sorted(p.stem for p in d.glob("*") if p.suffix.lower() in IMAGE_EXT) if d.exists() else []

    @staticmethod
    def _char_file(d: Path, expression: str) -> Path | None:
        if not d.exists():
            return None
        for name in [expression, *EXPRESSION_FALLBACK.get(expression, []), "normal"]:
            for ext in (".png", ".webp"):
                if (d / f"{name}{ext}").exists():
                    return d / f"{name}{ext}"
        return None

    def resolve_expression(self, char_id: str, expression: str) -> str:
        p = self.character(char_id, expression)
        return p.stem if p else expression


def fetch_pexels(keyword: str, api_key: str, cache_dir: Path) -> Path | None:
    """手持ち素材に無いキーワードの画像を Pexels から取得してキャッシュする(任意機能)。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.md5(keyword.encode()).hexdigest()[:10]
    cached = cache_dir / f"{name}.jpg"
    if cached.exists():
        return cached
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": keyword, "per_page": 1, "locale": "ja-JP"})
    try:
        req = urllib.request.Request(url, headers={"Authorization": api_key})
        with urllib.request.urlopen(req, timeout=15) as r:
            photos = json.load(r).get("photos", [])
        if not photos:
            return None
        with urllib.request.urlopen(photos[0]["src"]["large"], timeout=30) as r:
            cached.write_bytes(r.read())
        return cached
    except Exception as e:  # ネットワークエラー等は素材なしで続行
        print(f"[素材] Pexels 取得失敗 ({keyword}): {e}")
        return None
