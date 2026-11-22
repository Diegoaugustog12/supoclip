import pytest

from src import trending_tags
from src.post_copy import MAX_CHARS, clean_hashtags, trim_to_chars


def test_text_over_the_limit_is_cut_at_the_last_sentence():
    sentence = "Esta frase tem exatamente quarenta caracteres. "
    text = sentence * 100  # about 4,700 characters

    cut = trim_to_chars(text)

    assert len(cut) <= MAX_CHARS
    assert cut.endswith(".")
    assert len(cut) > MAX_CHARS - len(sentence)


def test_text_within_the_limit_is_untouched():
    assert trim_to_chars("um dois tres") == "um dois tres"


def test_text_without_sentence_ends_is_cut_by_characters():
    assert len(trim_to_chars("x" * (MAX_CHARS + 500))) == MAX_CHARS


def test_hashtags_are_cleaned_and_deduplicated():
    assert clean_hashtags(["#Viral", "viral", "#a b!", "#", "#gta6"]) == ["#Viral", "#ab", "#gta6"]


@pytest.mark.asyncio
async def test_trending_tags_count_one_vote_per_video(monkeypatch):
    class Config:
        @staticmethod
        def resolve_youtube_data_api_key():
            return "key"

    monkeypatch.setattr(trending_tags, "get_config", lambda: Config)
    monkeypatch.setattr(trending_tags, "_search_ids", lambda key, query, language: ["a", "b", "c"])
    monkeypatch.setattr(
        trending_tags,
        "_video_tags",
        lambda key, ids: [["gta", "gta", "humor"], ["gta", "fyp"], ["humor", "gta6"]],
    )

    ranked = await trending_tags.trending_tags(["gta 6 humor"], "pt")

    # "gta" twice in one video still counts once; "fyp" and "gta6" appear in a single video.
    assert ranked == [("gta", 2), ("humor", 2)]


@pytest.mark.asyncio
async def test_trending_tags_fall_back_to_nothing_on_failure(monkeypatch):
    class Config:
        @staticmethod
        def resolve_youtube_data_api_key():
            return "key"

    def boom(*args):
        raise RuntimeError("quota")

    monkeypatch.setattr(trending_tags, "get_config", lambda: Config)
    monkeypatch.setattr(trending_tags, "_search_ids", boom)

    assert await trending_tags.trending_tags(["x"]) == []
    assert await trending_tags.trending_tags([]) == []
