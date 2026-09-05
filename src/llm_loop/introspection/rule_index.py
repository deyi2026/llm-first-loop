"""On-demand index/hydration for the AI rule source of truth.

The full maintenance document stays out of the universal prompt.  This module only
projects mechanically parsed rule cards or one exact rule section; it never decides
whether a rule is relevant to the current task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

_RULE_REF_RE = re.compile(r"RULE-AI-\d+(?:\.\d+)?", re.IGNORECASE)
_RULE_HEADING_RE = re.compile(r"^##\s+.*?(RULE-AI-\d+(?:\.\d+)?).*?$", re.IGNORECASE | re.MULTILINE)
_QUERY_TOKEN_RE = re.compile(r"[\w.\-]+", re.UNICODE)


@dataclass(frozen=True)
class RuleEntry:
    ref: str
    title: str
    content: str
    synopsis: str
    order: int


class RuleIndex:
    """Content-hash cached mechanical view over ``docs/ai_rules.md``."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._digest = ""
        self._entries: tuple[RuleEntry, ...] = ()

    def search(self, query: str, limit: int) -> list[dict]:
        entries, digest = self._load()
        raw = str(query or "").strip()
        exact = self._exact_ref(raw)
        if exact:
            for entry in entries:
                if entry.ref == exact:
                    return [self._full_record(entry, digest)]
            return []
        if not raw:
            return [self._card(entry, digest) for entry in entries[:limit]]

        tokens = self._tokens(raw)
        ranked: list[tuple[int, int, RuleEntry]] = []
        for entry in entries:
            score = self._score(entry, tokens)
            if score > 0:
                ranked.append((-score, entry.order, entry))
        ranked.sort()
        return [self._card(entry, digest) for _, _, entry in ranked[:limit]]

    def _load(self) -> tuple[tuple[RuleEntry, ...], str]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            self._digest = ""
            self._entries = ()
            return self._entries, self._digest
        digest = sha256(text.encode()).hexdigest()
        if digest == self._digest:
            return self._entries, self._digest

        matches = list(_RULE_HEADING_RE.finditer(text))
        parsed: list[RuleEntry] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section = text[start:end].rstrip()
            heading = match.group(0).strip()
            ref = match.group(1).upper()
            parsed.append(
                RuleEntry(
                    ref=ref,
                    title=self._title(heading),
                    content=section,
                    synopsis=self._synopsis(section, heading),
                    order=index,
                )
            )
        self._digest = digest
        self._entries = tuple(parsed)
        return self._entries, self._digest

    @staticmethod
    def _exact_ref(query: str) -> str:
        match = _RULE_REF_RE.fullmatch(query.strip())
        return match.group(0).upper() if match else ""

    @staticmethod
    def _tokens(query: str) -> tuple[str, ...]:
        return tuple(token.casefold() for token in _QUERY_TOKEN_RE.findall(query) if token.strip())

    @staticmethod
    def _title(heading: str) -> str:
        return heading.removeprefix("##").strip()

    @staticmethod
    def _synopsis(section: str, heading: str) -> str:
        body = section[len(heading) :]
        for line in body.splitlines():
            clean = line.strip().strip("*-# ")
            if clean and clean != "---":
                return " ".join(clean.split())[:260]
        return ""

    @staticmethod
    def _score(entry: RuleEntry, tokens: tuple[str, ...]) -> int:
        if not tokens:
            return 1
        ref = entry.ref.casefold()
        title = entry.title.casefold()
        synopsis = entry.synopsis.casefold()
        body = entry.content.casefold()
        score = 0
        matched = 0
        for token in tokens:
            token_score = 0
            if token in ref:
                token_score = max(token_score, 12)
            if token in title:
                token_score = max(token_score, 8)
            if token in synopsis:
                token_score = max(token_score, 5)
            if token in body:
                token_score = max(token_score, 2)
            if token_score:
                matched += 1
                score += token_score
        # Multi-token queries are conjunctive enough to avoid noisy one-token hits.
        if len(tokens) > 1 and matched != len(tokens):
            return 0
        return score

    def _base(self, entry: RuleEntry, digest: str) -> dict:
        return {
            "kind": "rule",
            "ts": "",
            "id": entry.ref,
            "key": entry.ref,
            "rule_ref": entry.ref,
            "summary": entry.title,
            "synopsis": entry.synopsis,
            "source": str(self.path),
            "source_version_token": digest,
            "authority": "rule_sot",
            "task_applicability": "not_evaluated",
        }

    def _card(self, entry: RuleEntry, digest: str) -> dict:
        record = self._base(entry, digest)
        record.update({"representation": "rule_card", "projection_complete": False})
        return record

    def _full_record(self, entry: RuleEntry, digest: str) -> dict:
        record = self._base(entry, digest)
        record.update(
            {
                "hydrated": True,
                "representation": "full_rule",
                "projection_complete": True,
                "content": entry.content,
            }
        )
        return record
