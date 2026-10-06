from PIL import Image, ImageDraw

from ytedit.assets import AssetLibrary
from ytedit.characters import EXPRESSIONS, add_character, ensure_transparent


def _white_bg_char(path):
    img = Image.new("RGB", (400, 600), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((100, 50, 300, 280), fill=(90, 60, 40))   # 頭
    d.ellipse((180, 150, 200, 170), fill=(255, 255, 255))  # 目のハイライト(白だが内側なので残す)
    d.rectangle((140, 280, 260, 600), fill=(60, 140, 90))  # 体
    img.save(path)
    return path


def test_ensure_transparent_removes_only_outer_white(tmp_path):
    img = ensure_transparent(Image.open(_white_bg_char(tmp_path / "c.png")))
    assert img.getpixel((5, 5))[3] == 0
    assert img.getpixel((190, 160))[3] == 255  # 内側の白は残る
    assert img.getpixel((200, 400))[3] == 255


def test_add_character_generates_all_expressions(tmp_path):
    files = add_character("aoi", _white_bg_char(tmp_path / "c.png"), tmp_path / "assets")
    assert {p.stem for p in files} == set(EXPRESSIONS)
    sizes = {Image.open(p).size for p in files}
    assert len(sizes) == 1  # 全表情が同じキャンバス = 切り替えても位置がずれない
    lib = AssetLibrary(tmp_path / "assets")
    assert lib.character("aoi", "surprised").name == "surprised.png"
    # 手描き差分は上書きしない
    (tmp_path / "assets/characters/aoi/.generated").unlink()
    assert add_character("aoi", tmp_path / "c.png", tmp_path / "assets") == []
