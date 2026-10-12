"""Source-backed fact excerpts, without a model or inferred business truth."""

import hashlib
import json
import re
from dataclasses import dataclass

from aftercare_api.conversations.models import Message
from aftercare_api.conversations.token_budget import ContextBudgetError, TokenMeter

SUMMARY_VERSION = "fact-excerpts-v1"
ORDER_PATTERN = re.compile(
    r"(?:order(?:\s*(?:id|number|no\.?))?|订单(?:号)?)"
    r"[\s:#：-]*(?:(?:is|是)\s*)?([A-Za-z0-9_-]*\d[A-Za-z0-9_-]*)",
    re.IGNORECASE,
)
PATTERNS = {
    "order": ORDER_PATTERN,
    "product": re.compile(r"(?:product|商品)[\s:：]*([^,，。;\n]{1,80})", re.IGNORECASE),
    "date": re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日"),
    "quantity": re.compile(r"(?:quantity|数量)[\s:：]*(\d+)", re.IGNORECASE),
}


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def extract_facts(message: Message) -> list[dict[str, object]]:
    facts = []
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(message.content):
            facts.append(
                {
                    "kind": kind,
                    "value": match.group(1) if match.lastindex else match.group(),
                    "source_message_id": str(message.id),
                    "source_role": message.role,
                    "source_reply_version": message.reply_version,
                    "excerpt": match.group(),
                }
            )
    for sentence in re.split(r"[。！？\n]", message.content):
        if re.search(r"refund|return|退款|退货|换货|转人工", sentence, re.IGNORECASE):
            facts.append(
                {
                    "kind": "request",
                    "value": sentence,
                    "excerpt": sentence,
                    "source_message_id": str(message.id),
                    "source_role": message.role,
                    "source_reply_version": message.reply_version,
                }
            )
        if re.search(r"delivered|shipped|received|paid|签收|发货|付款", sentence, re.IGNORECASE):
            facts.append(
                {
                    "kind": "reported_status",
                    "value": sentence,
                    "excerpt": sentence,
                    "source_message_id": str(message.id),
                    "source_role": message.role,
                    "source_reply_version": message.reply_version,
                }
            )
    return facts


@dataclass
class SummaryDraft:
    fingerprint: str
    covered_message_ids: list[str]
    facts: list[dict[str, object]]
    content: str
    token_count: int


def summarize_turns(turns: list[tuple[Message, Message | None]], meter: TokenMeter, budget: int):
    """Preserve recognized user facts and fill remaining room with recent excerpts."""

    messages = [message for turn in turns for message in turn if message is not None]
    fingerprint = hashlib.sha256(
        compact_json(
            {
                "version": SUMMARY_VERSION,
                "encoding": meter.name,
                "tokenizer_version": meter.version,
                "budget": budget,
                "messages": [(str(message.id), message.content) for message in messages],
            }
        ).encode()
    ).hexdigest()
    # User statements stay user-reported; placeholder echoes add no verified facts.
    facts = [fact for user, _ in turns for fact in extract_facts(user)]
    snippets: list[dict[str, str]] = []
    content = compact_json({"facts": facts, "recent_excerpts": snippets})
    if meter.count(content) > budget:
        raise ContextBudgetError("Required facts exceed the summary budget")
    for user, _ in reversed(turns):
        snippet = {"source_message_id": str(user.id), "excerpt": user.content[:120]}
        candidate = compact_json({"facts": facts, "recent_excerpts": [snippet, *snippets]})
        if meter.count(candidate) <= budget:
            snippets.insert(0, snippet)
            content = candidate
    return SummaryDraft(
        fingerprint, [str(message.id) for message in messages], facts, content, meter.count(content)
    )
