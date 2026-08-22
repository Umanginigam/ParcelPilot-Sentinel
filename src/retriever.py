"""
STEP 4 — PDF -> sections -> BM25.

Retrieval is deliberately behind a stable interface:

    retrieve(query, account_id, include_all_accounts, k) -> ranked_sections

BM25 is an implementation detail. A future vector or hybrid implementation
can replace it without changing the agent or resolution engine.

Important separation:

    Retrieval  -> finds relevant text
    Registry   -> describes source authority/scope
    Resolution -> decides what actually governs

Retrieval may return deprecated/historical material as context, but those
sources are marked context_only and can never become the basis of a ruling.
Account-specific agreements are additionally scope-filtered here (defence in
depth): a customer only ever retrieves their own agreement + global docs, while
an authorised internal caller passes include_all_accounts=True to see everything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from rank_bm25 import BM25Okapi

from . import config as C
from .registry import SOURCES


# ---------------------------------------------------------------------------
# SECTION MODEL
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Section:
    doc_id: str
    heading: str
    text: str

    @property
    def source(self):
        return SOURCES.get(self.doc_id)


@dataclass(frozen=True)
class RankedSection:
    section: Section
    score: float

    # True means:
    # "This section may be shown as evidence/context, but the resolution
    # engine must not use it as the governing source."
    context_only: bool


# ---------------------------------------------------------------------------
# RETRIEVER INTERFACE
# ---------------------------------------------------------------------------

class Retriever(Protocol):

    def retrieve(
        self,
        query: str,
        account_id: str | None = None,
        include_all_accounts: bool = False,
        k: int = 5,
    ) -> list[RankedSection]:
        """
        Return the most relevant sections for the query.

        account_id:
            Customer account scope. Global documents are available to all
            callers; account-specific documents are only returned when the
            requested account matches their scope.

        include_all_accounts:
            Authorised internal callers set this True to bypass account
            scoping and retrieve every document, regardless of scope.

        Authority is NOT decided here.
        """
        ...


# ---------------------------------------------------------------------------
# TOKENIZATION
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """
    Lightweight tokenizer for the small terminology-heavy corpus.

    BM25 benefits from preserving domain terms such as:
        BOOKED
        P1
        SLA
        Northstar
        cancellation
        credit
    """

    return re.findall(r"[a-z0-9]+", text.lower())


# ---------------------------------------------------------------------------
# BM25 IMPLEMENTATION
# ---------------------------------------------------------------------------

class BM25Retriever:
    """
    Keyword retrieval over indexed document sections.

    BM25 is intentionally an implementation detail behind Retriever.
    """

    def __init__(self, sections: list[Section]):
        self._sections = sections

        corpus = [
            _tokenize(f"{section.heading} {section.text}")
            for section in sections
        ]

        self._bm25 = BM25Okapi(corpus)

    @classmethod
    def from_build(cls) -> "BM25Retriever":
        """
        Load preprocessed sections from build/sections.json.
        """

        raw = json.loads(
            C.SECTIONS_PATH.read_text(encoding="utf-8")
        )

        sections = [Section(**section) for section in raw]

        return cls(sections)

    def retrieve(
        self,
        query: str,
        account_id: str | None = None,
        include_all_accounts: bool = False,
        k: int = 5,
    ) -> list[RankedSection]:

        if not query.strip():
            return []

        scores = self._bm25.get_scores(_tokenize(query))

        order = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )

        results: list[RankedSection] = []

        for i in order:

            section = self._sections[i]
            source = section.source

            # ---------------------------------------------------------------
            # Scope filtering (defence in depth)
            # ---------------------------------------------------------------
            #
            # Skipped entirely for authorised internal callers
            # (include_all_accounts=True).
            #
            # Otherwise:
            #   - global documents are visible to everyone;
            #   - an account-specific agreement is only returned when the
            #     caller's account_id matches its scope.
            #
            if source is not None and not include_all_accounts:
                if source.scope != "global":
                    if account_id is None:
                        # No account context -> never expose an
                        # account-specific document.
                        continue
                    if source.scope != account_id:
                        continue

            # ---------------------------------------------------------------
            # Authority tagging
            # ---------------------------------------------------------------
            #
            # Deprecated policies / historical sources can still be useful
            # context, but cannot govern the final decision.
            #
            context_only = (
                source is None
                or not source.authoritative
            )

            results.append(
                RankedSection(
                    section=section,
                    score=float(scores[i]),
                    context_only=context_only,
                )
            )

            if len(results) >= k:
                break

        return results


# ---------------------------------------------------------------------------
# PDF -> SECTIONS BUILD
# ---------------------------------------------------------------------------

def build_sections() -> None:
    """
    Extract PDF text and split it into heading-delimited sections.

    Output:
        build/sections.json
    """

    import pymupdf

    C.BUILD_DIR.mkdir(parents=True, exist_ok=True)

    sections: list[dict] = []

    heading_re = re.compile(
        r"^\s*("
        r"\d+\.\s+\S.*"
        r"|"
        r"[A-Z][A-Za-z0-9 &/()\-]{3,}:?"
        r")\s*$"
    )

    for doc_id in SOURCES:

        pdf_path = C.DATA_DIR / doc_id

        if not pdf_path.exists():
            raise FileNotFoundError(f"Missing PDF: {pdf_path}")

        pdf = pymupdf.open(pdf_path)

        try:
            text = "\n".join(page.get_text() for page in pdf)
        finally:
            pdf.close()

        current_heading = "Preamble"
        buffer: list[str] = []

        for line in text.splitlines():

            line = line.strip()

            if heading_re.match(line) and len(line) < 80:

                if buffer:
                    sections.append(
                        {
                            "doc_id": doc_id,
                            "heading": current_heading,
                            "text": " ".join(buffer).strip(),
                        }
                    )

                current_heading = line
                buffer = []

            else:

                if line:
                    buffer.append(line)

        if buffer:
            sections.append(
                {
                    "doc_id": doc_id,
                    "heading": current_heading,
                    "text": " ".join(buffer).strip(),
                }
            )

    # Remove tiny/useless fragments.
    sections = [
        section
        for section in sections
        if len(section["text"]) > 20
    ]

    C.SECTIONS_PATH.write_text(
        json.dumps(sections, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Built {len(sections)} sections from {len(SOURCES)} documents.")