"""Conservative answer checks beyond exact quote matching, not an entailment model."""

import re

from .query_engine import words


def support_problem(text, citations, *, browser_code_only=False):
    quotes = " ".join(c["quote"] for c in citations if c.get("role") == "supporting")
    if not quotes:
        return "missing_support"
    # Dates, amounts and versions require literal support in the selected spans.
    numbers = re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", text)
    for number in numbers:
        if not re.search(r"(?<!\w)" + re.escape(number) + r"(?!\w)", quotes):
            return "unsupported_number"
    if browser_code_only and re.search(r"\b(?:the|its|original|actual) repository (?:is|has|uses|contains|structure)\b", text, re.I) and not re.search(r"\b(?:not|cannot|unknown|unestablished)\b", text, re.I):
        return "repository_scope"
    generic = {"source", "sources", "evidence", "retained", "analysis", "analyzed", "code", "application", "app", "web", "client", "platform", "system", "structure", "structured", "implemented", "relies", "based", "observed", "public", "supports", "provides"}
    def signals(value):
        return {w.removesuffix("s") for w in words(value) - generic if len(w) > 3}
    factual = signals(text)
    if len(factual) >= 4 and not factual & signals(quotes):
        return "unrelated_support"
    return ""


def requested_word_limit(question):
    match = re.search(r"\b(\d{1,4})\s*words?\b", question, re.I)
    return max(1, min(1000, int(match[1]))) if match else None


def response_preferences(question):
    """Guide one synthesis toward the requested depth; never manufacture a minimum."""
    requested = requested_word_limit(question)
    ceiling_only = bool(re.search(r"\b(?:under|within|maximum|max|at most|up to|no more than)\s+\d+\s*words?", question, re.I))
    brief = bool(re.search(r"\b(?:brief|briefly|short|shorter|concise|quick|briefer|one sentence)\b", question, re.I))
    detailed = bool(re.search(r"\b(?:detail(?:ed|s)?|deep(?:er)?|thorough|comprehensive|elaborate|expand|step by step)\b", question, re.I))
    explanatory = bool(re.search(r"\b(?:explain|understand|how|why|compare|overview|workflow|architecture|review|recommend|improve)\b", question, re.I))
    target = requested if requested and not ceiling_only else 80 if brief else 350 if detailed else 180 if explanatory else 90
    if requested:
        target = min(target, requested)
    return {
        "requested_words": requested,
        "target_words": target,
        "maximum_words": requested or (600 if detailed else 400),
        "format": "bullets" if re.search(r"\b(?:pointers|bullets|bullet points?)\b", question, re.I) else "prose",
        "depth": "detailed" if detailed else "brief" if brief else "explanation" if explanatory else "direct",
        "length_policy": "A ceiling only" if ceiling_only else "Aim close to the target when evidence supports it; do not pad or invent facts",
    }


def format_statements(statements, question):
    limit = requested_word_limit(question)
    bullets = bool(re.search(r"\b(?:pointers|bullets|bullet points?)\b", question, re.I))
    result, used = [], 0
    for statement in statements:
        text = statement["text"].strip()
        if limit:
            remaining = limit - used
            if remaining <= 0:
                break
            if len(text.split()) > remaining:
                sentences = re.split(r"(?<=[.!?])\s+", text)
                complete = []
                for sentence in sentences:
                    if sum(len(s.split()) for s in complete) + len(sentence.split()) > remaining:
                        break
                    complete.append(sentence)
                if not complete:
                    # Do not erase the direct answer when the model supplied a
                    # single long sentence. Keep it intact rather than fabricate
                    # a rewrite; requested lengths are visible in reply metadata.
                    if not result:
                        result.append({**statement, "text": ("• " if bullets else "") + sentences[0]})
                    break
                text = " ".join(complete)
        used += len(text.split())
        result.append({**statement, "text": ("• " if bullets and not text.startswith(("•", "- ")) else "") + text})
    return result
