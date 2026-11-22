"""The post description and hashtags for one clip.

The description runs 2,000 to 3,000 characters. It is written in one pass; when it comes out short it is
extended once, and past the maximum it is cut at the last full sentence. The hashtags come from tags that are
trending among recent top videos on the clip's own subject (``trending_tags``) when YouTube can be asked,
otherwise from the model.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput

from .trending_tags import trending_tags

logger = logging.getLogger(__name__)

MIN_CHARS = 2000
MAX_CHARS = 3000
TARGET_CHARS = 2500
EXTRA_PASSES = 3
TEXT_TIMEOUT_SECONDS = 90
HASHTAG_COUNT = 15


class PostPlan(BaseModel):
    """What to look up to find the tags that are hot in this clip's subject."""

    search_queries: List[str] = Field(description="2 or 3 short YouTube search queries about the clip's subject, as a viewer would type them")
    language: str = Field(description="ISO 639-1 code of the transcript language, e.g. pt, en, es")


class PostTags(BaseModel):
    hashtags: List[str] = Field(description="12 to 15 hashtags, each starting with #, no spaces")


plan_system_prompt = """You prepare the research for social media hashtags of one short video clip.
Read the title and transcript. Return 2 or 3 short search queries (2-5 words) a viewer interested in this clip's subject would type on YouTube,
from the most specific to the most general (game, topic, person or channel named in the transcript, and the kind of content), and the transcript's language code."""

text_system_prompt = f"""You write the post description that goes with one short vertical video clip (YouTube, TikTok, Instagram, Facebook).
Write in the same language as the clip transcript. Plain text only: no markdown symbols such as # or *, no hashtags, no emojis. Spell every word correctly with all the accents and special characters of the language.
Length: between {MIN_CHARS + 200} and {MAX_CHARS - 300} characters (spaces included). Count carefully: it must never be under {MIN_CHARS} or over {MAX_CHARS}.
Structure, as short paragraphs separated by blank lines:
1. A hook that makes people want to watch.
2. What happens in the clip, in the order it happens.
3. Who and what is involved (people, game, topic) and the context a fan would know.
4. Why the moment works (humor, tension, surprise), and a closing call to action (follow, comment, share).
Facts about the clip come ONLY from its transcript: never invent quotes, events, names, numbers or outcomes that are not there.
Background must be widely known and safe; if unsure of a detail, stay general instead of guessing."""

more_system_prompt = f"""You extend a post description for a short video clip. You get the current text and the clip transcript.
Return the FULL text again, in the same language and plain-text style (correct accents and special characters, no markdown, hashtags or emojis),
made longer with more detail from the transcript and the subject's context, so it ends between {MIN_CHARS + 200} and {MAX_CHARS - 300} characters.
Same rule on facts: the clip's own events only from the transcript."""

tags_system_prompt = f"""You choose hashtags for a short video clip. Write them in the language of the transcript when they are words, in lowercase without accents or spaces.
You get a list of TRENDING TAGS: tags used right now by the most viewed recent videos on the same subject, with how many of those videos use each.
- Pick {HASHTAG_COUNT} hashtags. Take at least 10 from the trending list: the ones that truly fit this clip, favoring those with more uses. Never pick a trending tag that does not match the clip.
- Fill the rest with tags about the clip's own topic and the people, game or channel named in the transcript.
- Never use misleading or unrelated tags.
If the trending list is empty, choose {HASHTAG_COUNT} tags yourself: 3-4 broad high-traffic ones, 5-6 about the topic and action, 3-4 about the people, game or channel, and 1-2 niche ones."""


class HookIdea(BaseModel):
    text: str = Field(description="The hook line, at most 70 characters, no hashtags, no emojis")
    style: str = Field(description="One word: question, shock, curiosity, story or bold")


class PostHooks(BaseModel):
    hooks: List[HookIdea] = Field(description="Exactly 5 alternative hooks, each with a different style")


hooks_system_prompt = """You write alternative opening hooks (the first line or on-screen title) for one short vertical video clip.
Write in the transcript's language. Give exactly 5 hooks, each a different style: question, shock, curiosity, story, bold.
Each is at most 70 characters, grounded ONLY in what happens in the clip, and never promises something the clip does not deliver."""


def char_count(text: str) -> int:
    return len(text)


def trim_to_chars(text: str, limit: int = MAX_CHARS) -> str:
    """Cut at the last full sentence (or paragraph) that fits in ``limit`` characters."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?…](?=\s|$)", head)]
    if ends and ends[-1] >= limit // 2:
        return head[: ends[-1]].rstrip()
    return head.rstrip()


def clean_hashtags(raw: List[str], limit: int = HASHTAG_COUNT) -> List[str]:
    seen: set[str] = set()
    tags: List[str] = []
    for item in raw:
        tag = "#" + re.sub(r"[^\w]", "", item.lstrip("#"), flags=re.UNICODE)
        if len(tag) > 1 and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return tags[:limit]


def _agent(ai, config, output_type, system_prompt):
    native = output_type is not str and ai._uses_native_output(config.llm)
    return Agent(
        model=ai._build_transcript_model(config, config.llm),
        output_type=NativeOutput(output_type, strict=True) if native else output_type,
        system_prompt=system_prompt,
        output_retries=2,
    )


async def write_text(ai, config, title: Optional[str], transcript: str) -> str:
    """One pass; extended while under ``MIN_CHARS``; always cut to ``MAX_CHARS``."""
    context = f"Clip title: {title or '(none)'}\nClip transcript:\n{transcript[:8000]}"
    writer = _agent(ai, config, str, text_system_prompt)
    text = str((await ai._run_transcript_analysis(writer, context, timeout_seconds=TEXT_TIMEOUT_SECONDS)).output).strip()
    extender = None
    for _ in range(EXTRA_PASSES):
        if len(text) >= MIN_CHARS:
            break
        extender = extender or _agent(ai, config, str, more_system_prompt)
        prompt = f"{context}\n\nCurrent text ({len(text)} characters, too short):\n{text}"
        longer = str((await ai._run_transcript_analysis(extender, prompt, timeout_seconds=TEXT_TIMEOUT_SECONDS)).output).strip()
        if len(longer) <= len(text):
            break
        text = longer
    return trim_to_chars(text)


async def write_hooks(ai, config, title: Optional[str], transcript: str) -> List[dict]:
    """Five alternative hooks in different styles; [] when the model cannot deliver (never fails the post copy)."""
    try:
        agent = _agent(ai, config, PostHooks, hooks_system_prompt)
        prompt = f"Current title: {title or '(none)'}\nClip transcript:\n{transcript[:4000]}"
        hooks = (await ai._run_transcript_analysis(agent, prompt, timeout_seconds=60)).output.hooks
    except Exception as error:
        logger.warning("Hook ideas skipped (%s)", type(error).__name__)
        return []
    return [{"text": hook.text.strip()[:90], "style": hook.style.strip().lower()[:20]} for hook in hooks if hook.text.strip()][:5]


async def write_tags(ai, config, title: Optional[str], transcript: str) -> tuple[List[str], bool]:
    """(hashtags, whether they were picked from trending tags)."""
    trending: list[tuple[str, int]] = []
    try:
        planner = _agent(ai, config, PostPlan, plan_system_prompt)
        plan = (await ai._run_transcript_analysis(
            planner, f"Clip title: {title or '(none)'}\nClip transcript:\n{transcript[:4000]}", timeout_seconds=60,
        )).output
        trending = await trending_tags(plan.search_queries, (plan.language or "").strip().lower()[:2] or None)
    except Exception as error:
        logger.warning("Trending tag research skipped (%s)", type(error).__name__)
    listing = "\n".join(f"#{tag} ({uses} videos)" for tag, uses in trending) or "(none available)"
    prompt = f"Clip title: {title or '(none)'}\nClip transcript:\n{transcript[:4000]}\n\nTRENDING TAGS:\n{listing}"
    chooser = _agent(ai, config, PostTags, tags_system_prompt)
    chosen = (await ai._run_transcript_analysis(chooser, prompt, timeout_seconds=60)).output
    return clean_hashtags(chosen.hashtags), bool(trending)
