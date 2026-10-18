"""Plan terms from explicitly headed comparison tables, with exact row anchors."""
import re


def commercial_facts(item):
    if item.source_type not in {"markdown", "text"} or not (item.category == "pricing" or re.search(r"(?im)^#{1,6}\s+.*(?:pricing|subscription plans|commercial plans)", item.content)):
        return
    from .document_facts import anchor_fact
    lines = list(re.finditer(r"(?m)^\s*\|[^\n]+\|\s*$", item.content))
    headers = None
    for line in lines:
        cells = [c.strip().strip("*") for c in line[0].strip().strip("|").split("|")]
        if cells and cells[0].casefold() in {"feature", "features", "capability", "capabilities"} and 2 <= len(cells) <= 10:
            headers = cells
            continue
        if not headers or len(cells) != len(headers) or not cells[0] or all(re.fullmatch(r"[: -]+", c) for c in cells):
            continue
        for tier, value in zip(headers[1:], cells[1:]):
            if re.fullmatch(r"(?:included|yes|available|unlimited|✓|✔)", value, re.I):
                availability, limitation = "included", ""
            elif re.fullmatch(r"(?:not included|no|unavailable|excluded|✗|✕|—)", value, re.I):
                availability, limitation = "excluded", ""
            elif re.match(r"(?:up to|limited to|maximum|\d+\s+)", value, re.I):
                availability, limitation = "limited", value
            else:
                continue
            yield anchor_fact(item, "feature", cells[0], cells[0] + " — " + tier + ": " + value, line.start(), line.end(), tier=tier[:80], availability=availability, limitation=limitation[:300], attributes={"commercial_scope": "declared", "source_path": item.source_url})
