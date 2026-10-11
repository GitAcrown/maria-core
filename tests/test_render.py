"""Les messages longs sont coupés sans dépasser la limite."""

from maria_core.ui.render import split_message


def test_short_text_is_one_chunk() -> None:
    assert split_message("  bonjour  ") == ("bonjour",)
    assert split_message("   ") == ()


def test_long_text_stays_within_the_limit_and_keeps_the_words() -> None:
    words = [f"mot{index:02d}" for index in range(80)]
    chunks = split_message(" ".join(words), limit=40)
    assert chunks
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert " ".join(chunks).split() == words


def test_a_cut_code_fence_is_closed_and_reopened() -> None:
    body = "avant\n```\n" + ("x" * 80) + "\n```\naprès"
    chunks = split_message(body, limit=40)
    assert chunks
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert "après" in chunks[-1]
