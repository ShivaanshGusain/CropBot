"""Source registry entries (registry/<slug>.toml), schema "Source registry".

An entry holds the Source node's fields plus what only the pipeline needs:
the local file, extraction settings, default-scope rules and section scopes.
`to_source()` builds the graph node from it.
"""

from typing import Literal

from pydantic import Field, PositiveInt, model_validator

from kg.schema.core import Model, Source, Text
from kg.schema.ids import RegionId, SourceId, StateId
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
    """A book rule such as "dose basis = per_ha unless stated" (pending schema v1.2: a list)."""
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

    @model_validator(mode="after")
    def _source_fields(self):
        self.to_source()                # url, sha256, language and edition checks live on Source
        if self.supersedes == self.id:
            raise ValueError("a source cannot supersede itself")
        return self
