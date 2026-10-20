"""Source registry entries (registry/<slug>.toml), schema "Source registry".

An entry holds the Source node's fields plus what only the pipeline needs:
the local file, extraction settings, default-scope rules and section scopes.
`to_source()` builds the graph node from it.
"""

from typing import Literal

from pydantic import Field, PositiveInt, model_validator

from kg.schema.core import Model, Source, Text
from kg.schema.ids import CropId, RegionId, SourceId, StateId
from kg.schema.vocab import AuthorityTier

RuleStatus = Literal["proposed", "approved", "rejected"]


class Section(Model):
    """A section, keyed by heading text and PDF page range (heading levels are unreliable)."""
    heading: Text
    pdf_pages: tuple[PositiveInt, PositiveInt]

    @model_validator(mode="after")
    def _order(self):
        if self.pdf_pages[0] > self.pdf_pages[1]:
            raise ValueError("pdf_pages start %d is after end %d" % self.pdf_pages)
        return self


class DefaultScopeRule(Model):
    """A book rule such as "dose basis = per_ha unless stated" (schema v1.2: a list)."""
    rule: Text
    quote: Text
    pdf_page: PositiveInt
    status: RuleStatus
    section: Section | None = None      # None = the whole book

    def label(self) -> str:
        where = "%s, PDF pp. %d-%d" % ((self.section.heading,) + self.section.pdf_pages) \
            if self.section else "whole book"
        return "%s [%s]" % (self.rule, where)


class SectionScope(Section):
    """Section -> regions override (schema: "Section overrides")."""
    regions: list[RegionId] = Field(min_length=1)
    status: RuleStatus


class PrintedPages(Model):
    """A run of PDF pages whose printed page number is PDF page - offset."""
    pdf_pages: tuple[PositiveInt, PositiveInt]
    offset: int

    @model_validator(mode="after")
    def _order(self):
        if self.pdf_pages[0] > self.pdf_pages[1]:
            raise ValueError("pdf_pages start %d is after end %d" % self.pdf_pages)
        if self.pdf_pages[0] - self.offset < 1:
            raise ValueError("offset %d gives a printed page below 1" % self.offset)
        return self


class Chapter(Model):
    """A contents-table entry. Segmentation uses every chapter for boundaries;
    extraction uses approved chapters only."""
    number: Text
    title: Text
    group: str | None = None            # "MILLETS" for Sorghum, Cumbu, ...
    printed_page: PositiveInt
    pdf_page: PositiveInt
    status: RuleStatus
    crop_id: CropId | None = None       # used only once the chapter is approved

    def path_label(self) -> str:
        return "%s > %s" % (self.group, self.title) if self.group else self.title


class HeadingFix(Model):
    """A reviewed correction to one Docling item (nothing is auto-corrected).

    `match` is the item text as converted, found exactly once on `pdf_page`.
      kind = "split":   the heading `match` becomes `heading`; the rest becomes an inline
                        sub-heading of it, or a sub-section (numbered or not).
      kind = "restore": the item `match` (often a list item whose number Docling dropped)
                        becomes the heading `heading` as printed, e.g.
                        "Harvesting" -> "1.5. Harvesting".
    """
    kind: Literal["split", "restore"] = "split"
    match: Text
    pdf_page: PositiveInt
    heading: Text
    inline_subheading: str | None = None
    subsection: str | None = None
    status: RuleStatus
    note: str | None = None

    @model_validator(mode="after")
    def _shape(self):
        rest = [x for x in (self.inline_subheading, self.subsection) if x]
        if self.kind == "restore":
            from kg.segment.numbering import parse
            if rest:
                raise ValueError("a restore fix has no inline_subheading or subsection")
            number, title = parse(self.heading)
            if number is None or title != self.match:
                raise ValueError("restore heading %r must be a number followed by the match %r"
                                 % (self.heading, self.match))
            return self
        if len(rest) != 1:
            raise ValueError("a split heading_fix needs exactly one of inline_subheading or subsection")
        if self.match != "%s %s" % (self.heading, rest[0]):
            raise ValueError("match %r must equal heading + ' ' + %r" % (self.match, rest[0]))
        return self


class ReadingOrderFix(Model):
    """A reviewed correction to Docling's reading order on one page: the items from `first`
    to `last` (inclusive, as converted) move to just after the item `after`. Each text must
    be found exactly once on `pdf_page`."""
    pdf_page: PositiveInt
    first: Text
    last: Text
    after: Text
    status: RuleStatus
    note: str | None = None


class Extraction(Model):
    """Conversion settings carried over from extraction/sources.toml."""
    ocr: Literal["auto", "force"] = "auto"
    ocr_lang: list[str] = ["en"]
    page_range: tuple[PositiveInt, PositiveInt] | None = None
    crop: str | None = None             # single-crop books
    note: str | None = None


class RegistryEntry(Model):
    id: SourceId
    title: Text
    publisher: Text
    edition_year: int
    edition_label: Text
    language: str
    url: str
    sha256: str
    file: Text                          # local path, relative to the repo root
    state_id: StateId | None = None
    region_scope: list[RegionId] = Field(min_length=1)
    authority_tier: AuthorityTier
    doc_type: Text
    rights_note: str | None = None
    supersedes: SourceId | None = None  # an older edition of the same book
    notes: list[str] = []               # known problems with the file, e.g. missing pages
    printed_pages: list[PrintedPages] = []
    chapters: list[Chapter] = []
    heading_fix: list[HeadingFix] = []
    reading_order_fix: list[ReadingOrderFix] = []
    extraction: Extraction = Extraction()
    default_scope: list[DefaultScopeRule] = []
    section_scope: list[SectionScope] = []

    def to_source(self) -> Source:
        """The graph node. Only approved default-scope rules are carried."""
        return Source(
            id=self.id, title=self.title, publisher=self.publisher,
            edition_year=self.edition_year, edition_label=self.edition_label,
            language=self.language, url=self.url, sha256=self.sha256,
            state_id=self.state_id, region_scope=self.region_scope,
            authority_tier=self.authority_tier,
            default_scope=[r.label() for r in self.default_scope if r.status == "approved"],
        )

    def approved_section_scopes(self) -> list[SectionScope]:
        return [s for s in self.section_scope if s.status == "approved"]

    def printed_page(self, pdf_page: int) -> str | None:
        """The page number printed in the book, or None outside the printed_pages runs."""
        for run in self.printed_pages:
            if run.pdf_pages[0] <= pdf_page <= run.pdf_pages[1]:
                return str(pdf_page - run.offset)
        return None

    @model_validator(mode="after")
    def _source_fields(self):
        self.to_source()                # url, sha256, language and edition checks live on Source
        if self.supersedes == self.id:
            raise ValueError("a source cannot supersede itself")
        runs = sorted(r.pdf_pages for r in self.printed_pages)
        for (_, end), (start, _) in zip(runs, runs[1:]):
            if start <= end:
                raise ValueError("printed_pages runs overlap at PDF page %d" % start)
        for ch in self.chapters:
            if self.printed_page(ch.pdf_page) != str(ch.printed_page):
                raise ValueError("chapter %s %r: PDF p. %d is printed p. %s, not %d" % (
                    ch.number, ch.title, ch.pdf_page, self.printed_page(ch.pdf_page), ch.printed_page))
        numbers = [ch.number for ch in self.chapters]
        if len(numbers) != len(set(numbers)):
            raise ValueError("duplicate chapter numbers")
        return self
