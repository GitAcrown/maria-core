"""Catalogue des décisions. Les phases suivantes les appellent, le moteur est déjà là."""

from collections.abc import Callable, Mapping
from typing import Any, Literal

from maria_core.decisions.registry import Decision
from maria_core.decisions.rules import (
    address_rules,
    ambient_rules,
    claim_rules,
    condition_rules,
    draft_rules,
    followup_rules,
    intent_rules,
    join_rules,
    listen_rules,
    memory_worth_rules,
    price_rules,
    reaction_rules,
    request_rules,
    sensitivity_rules,
    topic_rules,
)
from maria_core.decisions.types import Question, RuleHit

type Rule = Callable[[Mapping[str, Any]], RuleHit | None]


def builtin_decisions() -> tuple[Decision, ...]:
    return (
        _decision(
            "addressed_to_bot",
            fallback="ignore",
            threshold=0.65,
            budget=400,
            ttl=120,
            rules=address_rules,
            instructions=(
                "The bot `bot_name` is named mid-sentence in `text`. "
                "respond only if the author addresses her. "
                "ignore if they talk about her in the third person."
            ),
            criteria={
                "respond": "Question, request, greeting, or tu/toi directed at her",
                "ignore": "Talking about her, a name list, or no reason for her to answer",
                "react": "A nod would do, words would be too much",
            },
        ),
        _decision(
            "draft_reply",
            fallback="ask",
            threshold=0.6,
            budget=200,
            ttl=30,
            rules=draft_rules,
            instructions="Does `text` accept, reject, or stay ambiguous about a pending draft?",
            criteria={
                "accept": "Yes, ok, go ahead",
                "reject": "No, stop, cancel",
                "ask": "Ambiguous or about something else",
            },
        ),
        _decision(
            "listen_relevance",
            fallback="ignore",
            threshold=0.65,
            budget=400,
            ttl=30,
            rules=listen_rules,
            instructions=(
                "`message` contains the phrase `pattern`, the exact name of a title, person or "
                "thing someone asked to be warned about. fire only if the message really refers "
                "to that thing, not to the same words used in another sense."
            ),
            criteria={
                "fire": "Genuinely about the watched topic",
                "ignore": "Passing mention, joke, or another sense of the word",
            },
        ),
        _decision(
            "condition_judge",
            fallback=False,
            threshold=0.6,
            budget=200,
            ttl=0,
            rules=condition_rules,
            kind="noul",
            instructions="Is `condition` true given `evidence`?",
            criteria={"true": "The evidence satisfies the condition", "false": "It does not"},
        ),
        _decision(
            "main_price",
            fallback="0",
            threshold=0.55,
            budget=100,
            ttl=0,
            rules=price_rules,
            instructions="Which snippet index is the product price, not shipping or a discount?",
            criteria={"0": "First snippet", "1": "Second", "2": "Third", "3": "Fourth"},
        ),
        _decision(
            "intent",
            fallback="none",
            threshold=0.5,
            budget=800,
            ttl=300,
            rules=intent_rules,
            instructions="What is the main tool category of `text`, if any?",
            criteria={
                "none": "Chat, no live tool",
                "web": "Needs a web search or a page",
                "weather": "Weather",
                "tasks": "A reminder, watch, or recurring task",
                "images": "About an attached or requested image",
            },
        ),
        _decision(
            "memory_worth_proposing",
            fallback=False,
            threshold=0.6,
            budget=200,
            ttl=60,
            rules=memory_worth_rules,
            kind="noul",
            instructions="Is `text` a durable fact worth proposing to remember?",
            criteria={"true": "Stable personal or server fact", "false": "Chatter or one-off"},
        ),
        _decision(
            "objective_request",
            fallback=False,
            threshold=0.7,
            budget=300,
            ttl=60,
            rules=request_rules,
            kind="noul",
            instructions=(
                "Is the author of `text` explicitly asking the bot to notify, ping, remind or "
                "watch something for them? A remark, a reaction, a joke, a question, or merely "
                "naming a topic is NOT a request."
            ),
            criteria={
                "true": "They clearly ask to be warned, pinged, reminded or to have it watched",
                "false": "A remark, chat, a question, or a topic named in passing",
            },
        ),
        _decision(
            "fact_sensitivity",
            fallback="ordinary",
            threshold=0.7,
            budget=300,
            ttl=3600,
            rules=sensitivity_rules,
            instructions=(
                "`text` is a fact someone told a chat bot about themselves. sensitive if it "
                "touches health, mental health, sexuality, religion, politics, money, legal "
                "trouble, family conflict or anything they might regret having stored."
            ),
            criteria={
                "sensitive": "Health, sexuality, religion, politics, money, justice, intimate life",
                "ordinary": "Tastes, hobbies, work, places, habits, pets, everyday life",
            },
        ),
        _decision(
            "memory_conflict",
            fallback="keep",
            threshold=0.65,
            budget=300,
            ttl=600,
            rules=None,
            instructions=(
                "`old` is a stored fact about a person, `new` is what they just said. "
                "replace only if `new` updates or contradicts `old` (same subject, only one can "
                "be true now). keep if both can be true at once."
            ),
            criteria={
                "replace": "Same subject, the new fact supersedes or contradicts the old one",
                "keep": "Different subject, or both facts can be true together",
            },
        ),
        _decision(
            "claim_check",
            fallback="grounded",
            threshold=0.7,
            budget=300,
            ttl=300,
            rules=claim_rules,
            instructions=(
                "`answer` is what a chat bot replied to `question` WITHOUT looking anything up. "
                "needs_check only if it states specific current or recent facts that memory "
                "cannot guarantee (news, scores, prices, who currently holds a role, weather, "
                "recent dates). Opinions, jokes, chat, maths and timeless knowledge are grounded."
            ),
            criteria={
                "grounded": "General knowledge, chat, opinion, maths, or nothing time-sensitive",
                "needs_check": "Specific current or recent facts that should be looked up",
            },
        ),
        _decision(
            "followup",
            fallback="ignore",
            threshold=0.58,
            budget=400,
            ttl=15,
            rules=followup_rules,
            instructions=(
                "The bot just answered `bot_last` to this author. Does `text` continue that "
                "exchange with the bot (reply, follow-up question, thanks needing an answer)?"
            ),
            criteria={
                "respond": "It answers or questions the bot",
                "react": "An acknowledgement, a nod would do",
                "ignore": "New topic, or talking to someone else",
            },
        ),
        _decision(
            "ambient_react",
            fallback=False,
            threshold=0.68,
            budget=200,
            ttl=20,
            rules=ambient_rules,
            kind="noul",
            instructions=(
                "Friends chat on Discord. Should the bot add an emoji reaction to `text` "
                "without being asked? Only if it is clearly natural (joke, good news, vibe)."
            ),
            criteria={"true": "A reaction clearly fits", "false": "Stay quiet"},
        ),
        _decision(
            "pick_reaction",
            fallback="0",
            threshold=0.5,
            budget=200,
            ttl=20,
            rules=reaction_rules,
            instructions="Which option best reacts to `text`?",
            criteria={"0": "First option", "1": "Second", "2": "Third"},
        ),
        _decision(
            "join_reaction",
            fallback=False,
            threshold=0.55,
            budget=200,
            ttl=20,
            rules=join_rules,
            kind="noul",
            instructions=(
                "`humans` people reacted `emoji` to `text`. Should the bot join with the same "
                "emoji, like a friend would?"
            ),
            criteria={"true": "Join", "false": "Do not"},
        ),
        _decision(
            "topic_match",
            fallback="ignore",
            threshold=0.65,
            budget=600,
            ttl=30,
            rules=topic_rules,
            instructions=(
                "Someone asked to be alerted when people talk about `topic`. "
                "Is `message` really about that topic?"
            ),
            criteria={"fire": "Clearly about the topic", "ignore": "Not about it"},
        ),
    )


def _decision(
    name: str,
    *,
    fallback: object,
    threshold: float,
    budget: int,
    ttl: float,
    rules: Rule | None,
    instructions: str,
    criteria: dict[str, str],
    kind: Literal["choice", "noul"] = "choice",
) -> Decision:
    return Decision(
        name=name,
        threshold=threshold,
        fallback=fallback,
        rules=rules,
        backend="structured",
        cache_ttl_s=ttl,
        budget_per_day=budget,
        question=Question(
            instructions=instructions,
            criteria=criteria,
            kind=kind,
            field="answer",
        ),
    )
