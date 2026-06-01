"""Lightweight routing hints for chat requests that need tools.

These patterns are intentionally conservative. They only classify action
requests, not explanatory questions about how a feature works.

The classifier distinguishes direct tools from agent tools:
- direct_tool: deterministic app data/actions that the backend can run without
  asking the LLM to choose a tool.
- agent_tool: actions that should promote plain chat to agent mode because the
  model needs planning/context before selecting tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Literal, Mapping, Pattern


ToolIntentKind = Literal["direct_tool", "agent_tool"]


@dataclass(frozen=True)
class ToolIntent:
    kind: ToolIntentKind
    tool: str = ""
    args: Mapping[str, Any] = field(default_factory=dict)


_ACTION_QUESTION = r"\b(?:can|could|would|will)\s+you\s+"
_PLEASE = r"^\s*(?:please\s+)?"

_CALENDAR_ACTION = r"(?:add|create|schedule|book|put|set\s+up|make)"
_CALENDAR_THING = r"(?:calendar|calendar\s+(?:entry|item)|event|meeting|appointment|entry|call)"

_PANEL = (
    r"(?:calendar|notes?|inbox|email|mail|documents?|docs|library|gallery|"
    r"settings|cookbook|sessions?|chats?|skills|memories|memory|brain)"
)

_BILLING_INTENT_PATTERN_TEXTS = (
    r"^\s*/billing\b",
    r"\b(?:show|draw|create|make|display)\b.{0,80}\b(?:spend|spending|billing|costs?|budget)\b.{0,80}\b(?:graph|chart|plot|breakdown)\b",
    r"\b(?:spend|spending|billing|costs?|budget)\b.{0,80}\b(?:graph|chart|plot|breakdown)\b",
    r"\b(?:spend|spending|billing|costs?|budget)\b.{0,80}\bforecast\b",
    r"\bforecast\b.{0,80}\b(?:spend|spending|billing|costs?|budget)\b",
    r"\b(?:spend|spending|billing|costs?|budget)\b.{0,80}\b(?:by|per)\s+(?:model|provider)\b",
    r"\b(?:current|monthly|month-to-date)\b.{0,80}\b(?:spend|spending|billing|costs?)\b",
)

def _compile_patterns(patterns: Iterable[str]) -> tuple[Pattern[str], ...]:
    return tuple(re.compile(pattern, re.I) for pattern in patterns)


_BILLING_INTENT_PATTERNS = _compile_patterns(_BILLING_INTENT_PATTERN_TEXTS)

_BILLING_PERIOD_ARG_PATTERNS = (
    ("day", _compile_patterns((r"\b(?:today|daily|day)\b",))),
    ("month", _compile_patterns((r"\b(?:month|monthly|month-to-date|forecast)\b",))),
)

_BILLING_GROUP_ARG_PATTERNS = (
    (
        "model",
        _compile_patterns((
            r"\b(?:by|per)\s+model\b",
            r"\bmodel\s+(?:breakdown|costs?|spend)\b",
        )),
    ),
    (
        "provider",
        _compile_patterns((
            r"\b(?:by|per)\s+provider\b",
            r"\bprovider\s+(?:breakdown|costs?|spend)\b",
        )),
    ),
)

_BILLING_PROVIDER_PATTERN = re.compile(
    r"\bprovider\s+(?P<provider>(?!breakdown\b|costs?\b|spend\b|graph\b|chart\b)[a-z0-9_.-]+)\b",
    re.I,
)

_AGENT_TOOL_INTENT_PATTERN_TEXTS = (
    # Calendar/event creation. Covers "Can you add an entry to my
    # calendar?" and imperatives like "add lunch to my calendar".
    rf"{_ACTION_QUESTION}{_CALENDAR_ACTION}\b.{{0,120}}\b{_CALENDAR_THING}\b",
    rf"{_PLEASE}{_CALENDAR_ACTION}\b.{{0,120}}\b(?:to|on|in|into|for)\s+(?:my\s+|the\s+|this\s+)?calendar\b",
    rf"{_PLEASE}{_CALENDAR_ACTION}\s+(?:a\s+|an\s+)?(?:calendar\s+)?(?:event|meeting|appointment|entry|item|call)\b",
    r"\bput\s+.+\bon\s+(?:my\s+)?calendar\b",

    # Notes, todos, checklists, and reminders.
    r"\bremind\s+me\b",
    rf"{_ACTION_QUESTION}(?:add|create|make|take|jot|write\s+down|set)\b.{{0,120}}\b(?:note|todo|task|checklist|reminder)\b",
    rf"{_PLEASE}(?:add|create|make)\s+(?:a\s+|an\s+)?(?:todo|task|reminder|note|checklist)\b",
    rf"{_PLEASE}(?:take|jot|write\s+down)\s+(?:a\s+|an\s+)?note\b",
    rf"{_PLEASE}(?:add|jot|write\s+down)\b.{{0,120}}\b(?:to|in|into)\s+(?:my\s+|the\s+)?(?:todo(?:\s+list)?|task\s+list|notes?|checklist)\b",
    rf"{_PLEASE}set\s+(?:a\s+)?reminder\b",
    rf"{_ACTION_QUESTION}set\s+(?:a\s+)?reminder\b",

    # Email actions.
    rf"{_ACTION_QUESTION}(?:send|write|reply|email|message|archive|delete|mark)\b.{{0,120}}\b(?:emails?|mail|messages?|inbox|unread|read)\b",
    rf"{_PLEASE}(?:send|write|reply)\b.{{0,120}}\b(?:emails?|mail|messages?)\b",
    rf"{_PLEASE}(?:archive|delete|mark)\b.{{0,120}}\b(?:emails?|mail|messages?|inbox)\b",
    r"\b(?:send|write|reply)\s+(?:an?\s+)?(?:email|message|mail)\b",
    r"\bemail\s+\w+\b",
    r"\bcheck\s+(?:my\s+)?(?:email|inbox|mail)\b",
    r"\bunread\s+(?:email|mail)s?\b",

    # UI/control-plane actions that should open panels or flip toggles.
    rf"{_PLEASE}(?:open|show|bring\s+up)\s+(?:me\s+)?(?:my\s+|the\s+)?{_PANEL}\b",
    r"\b(?:disable|enable|turn\s+(?:on|off))\s+(?:the\s+)?(?:shell|search|web|browser|documents?|memory|skills|images?|calendar|email|mail|research|incognito)\b",

    # Deep research jobs, not quick conceptual mentions of research.
    rf"{_PLEASE}(?:research|deep\s+dive|look\s+into|investigate)\s+.+",
    rf"{_ACTION_QUESTION}(?:research|do\s+research|deep\s+dive|look\s+into|investigate)\s+.+",

    # Shell / remote-host intent.
    r"\bssh\s+(?:in)?to\b",
    r"\bssh\s+\w+",
    r"\b(run|execute)\s+.{1,40}\bon\s+\w+",
    r"\b(can|could|please|would)\s+you\s+(run|execute|exec)\b",
    r"\b(deploy|build|install|restart|reboot|kill|tail|grep|cat|ls|cd|cp|mv|rm)\b\s+\S+",
    r"\b(check|see)\s+(if|whether|what)\s+.{1,40}\b(running|process|service|port|file|exists?)\b",
)

_AGENT_TOOL_INTENT_PATTERNS: tuple[Pattern[str], ...] = tuple(
    re.compile(pattern, re.I)
    for pattern in _AGENT_TOOL_INTENT_PATTERN_TEXTS
)

_TOOL_INTENT_PATTERNS: tuple[Pattern[str], ...] = (
    *_BILLING_INTENT_PATTERNS,
    *_AGENT_TOOL_INTENT_PATTERNS,
)


def _matches(text: str, patterns: Iterable[Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _matching_arg_value(text: str, rules: Iterable[tuple[str, Iterable[Pattern[str]]]]) -> str | None:
    for value, patterns in rules:
        if _matches(text, patterns):
            return value
    return None


def _billing_intent_args(text: str) -> dict[str, Any]:
    normalized = text.lower()
    args: dict[str, Any] = {"action": "spending_graph", "refresh": True}

    period = _matching_arg_value(normalized, _BILLING_PERIOD_ARG_PATTERNS)
    if period:
        args["period"] = period

    group_by = _matching_arg_value(normalized, _BILLING_GROUP_ARG_PATTERNS)
    if group_by:
        args["group_by"] = group_by

    provider_match = _BILLING_PROVIDER_PATTERN.search(normalized)
    if provider_match:
        args["provider"] = provider_match.group("provider")

    return args


def classify_tool_intent(text: str) -> ToolIntent | None:
    """Return the specific tool intent needed by chat routing, if any."""
    if not text:
        return None
    if _matches(text, _BILLING_INTENT_PATTERNS):
        return ToolIntent(
            kind="direct_tool",
            tool="manage_billing",
            args=_billing_intent_args(text),
        )
    if _matches(text, _AGENT_TOOL_INTENT_PATTERNS):
        return ToolIntent(kind="agent_tool")
    return None


def message_needs_tools(text: str, patterns: Iterable[Pattern[str]] | None = None) -> bool:
    """Return True when a plain chat message should be promoted to agent mode."""
    if not text:
        return False
    if patterns is not None:
        return _matches(text, patterns)
    return classify_tool_intent(text) is not None
