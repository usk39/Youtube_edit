import pytest

from ytedit import linebreak
from ytedit.linebreak import NO_LINE_START, break_text, tidy


def _check(pages, max_chars):
    for lines in pages:
        assert 1 <= len(lines) <= 2
        for l in lines:
            assert len(l) <= max_chars
            assert l[0] not in NO_LINE_START  # 禁則
    return ["".join(p) for p in pages]


def test_short_text_stays_one_line():
    assert break_text("今日は円安の話題よ。", 18) == [["今日は円安の話題よ。"]]


def test_two_lines_break_at_natural_point():
    pages = break_text("あおい、今日はね、円安と物価の話題についてよ。", 18)
    assert pages == [["あおい、今日はね、", "円安と物価の話題についてよ。"]]


def test_long_text_split_into_pages_at_sentence_end():
    text = "あおい、今日はね、円安と物価の話題についてよ。実は、なんと過去最大の値上げなの！"
    pages = break_text(text, 18)
    joined = _check(pages, 18)
    assert "".join(joined) == text
    assert joined[0].endswith("。")  # 文の終わりでページを分ける


def test_no_space_at_line_start():
    pages = break_text("えっ、まじで!? また値上げとか、ふざけとるやろ。", 18)
    assert all(not l.startswith(" ") for p in pages for l in p)


@pytest.mark.parametrize("use_budoux", [True, False])
def test_heuristic_and_budoux_respect_limits(monkeypatch, use_budoux):
    if not use_budoux:
        monkeypatch.setattr(linebreak, "_budoux", lambda: None)
    text = "政府は来年度から消費税の軽減税率の対象品目を見直す方針を固めたと発表したの。ネットでは「また増税か」と批判が相次いでいるよ。"
    joined = _check(break_text(text, 16), 16)
    assert "".join(joined) == text


def test_tidy():
    assert tidy("話題についてよ。") == "話題についてよ"
    assert tidy("ええ、そうなの。", "space") == "ええ　そうなの"
    assert tidy("そうなの。", "keep") == "そうなの。"
