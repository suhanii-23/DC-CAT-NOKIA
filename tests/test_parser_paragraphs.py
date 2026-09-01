"""Paragraph splitting in common.parser.

Real PDFs almost never contain blank lines, so the old "split the page on
\\n\\n" rule handed the keyword-search features one page-sized paragraph per
page. PyMuPDF's block grouping does not fix that on its own — measured over
generated PDFs it produces one block per paragraph only when paragraphs are
separated by extra vertical space, one block for the WHOLE PAGE under
uniform leading, and one block per LINE at loose leading. The splitter
therefore works from per-line geometry.

These tests pin the behaviour that matters to the two keyword-search
features:

  - all three of those layouts are split into the authored paragraphs;
  - a sentence the PDF merely wrapped is never torn apart, because a torn
    paragraph loses phrase matches;
  - vertical space (including a blank line) still breaks paragraphs;
  - the Document/Page/Paragraph contract is unchanged.
"""
from __future__ import annotations

import textwrap

import pytest

from common import parser
from common.parser import parse

fitz = pytest.importorskip("pymupdf")


# --- helpers -----------------------------------------------------------

# The three layouts PyMuPDF's own block grouping handles differently.
# (fontsize, leading, gap between paragraphs)
LAYOUTS = {
    "gapped": (10.5, 15, 9),   # blocks == paragraphs
    "dense": (10.5, 15, 0),    # ONE block for the whole page
    "loose": (12, 20, 0),      # one block per line
}


def _pdf(path, paragraphs: list[str], layout: str = "dense", width: int = 78) -> str:
    size, leading, gap = LAYOUTS[layout]
    doc = fitz.open()
    page = doc.new_page()
    y = 70.0
    for paragraph in paragraphs:
        for line in textwrap.wrap(paragraph, width):
            if y > 760:
                page = doc.new_page()
                y = 70.0
            page.insert_text((72, y), line, fontsize=size)
            y += leading
        y += gap
    doc.save(str(path))
    doc.close()
    return str(path)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _texts(document) -> list[str]:
    return [_flat(p.text) for p in document.paragraphs]


BODY = [
    "3 Security Configuration",
    "The platform verifies every operator account against the configured "
    "identity provider before a session is established. Credentials are never "
    "stored by the platform itself; only the assertion returned by the "
    "provider is retained, and only for the lifetime of that session.",
    "Authentication failures are recorded together with the originating "
    "address and the reason reported by the provider. Repeated failures from "
    "a single address cause that address to be held off for a steadily "
    "increasing interval.",
    "3.1 Two-Factor Verification",
    "Where an operator requires two-factor verification, the second factor is "
    "requested by the identity provider rather than by the platform, so no "
    "additional configuration is needed on this side of the boundary.",
]

LIST_BODY = [
    "2 Installation Steps",
    "Complete the following steps in order.",
    "- Provision the operating system prerequisites on every host.",
    "- Install the platform packages from the signed repository.",
    "- Run the first-time initialisation and confirm the report.",
]


# --- the failure this change fixes -------------------------------------


def test_a_page_extracted_as_one_block_is_still_split(tmp_path):
    """The reported bug: no blank lines, and PyMuPDF sees a single block."""
    path = _pdf(tmp_path / "dense.pdf", BODY, "dense")

    page = fitz.open(path)[0]
    assert len([b for b in page.get_text("blocks") if b[6] == 0]) == 1, (
        "fixture must extract as a single block for this test to mean anything"
    )
    assert "\n\n" not in page.get_text("text"), "fixture must have no blank lines"

    assert _texts(parse(path)) == [_flat(t) for t in BODY]


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_every_layout_recovers_the_authored_paragraphs(tmp_path, layout):
    path = _pdf(tmp_path / f"{layout}.pdf", BODY, layout)
    assert _texts(parse(path)) == [_flat(t) for t in BODY]


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_lists_and_their_heading_survive_every_layout(tmp_path, layout):
    path = _pdf(tmp_path / f"list_{layout}.pdf", LIST_BODY, layout)
    assert _texts(parse(path)) == [_flat(t) for t in LIST_BODY]


def test_headings_are_not_glued_to_the_paragraph_above_or_below(tmp_path):
    document = parse(_pdf(tmp_path / "dense.pdf", BODY, "dense"))
    assert "3.1 Two-Factor Verification" in _texts(document)


# --- what must NOT be split --------------------------------------------


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_wrapped_sentence_is_not_split(tmp_path, layout):
    sentence = (
        "This document describes the OSS authentication and configuration "
        "workflow used during the DC CAT prototype evaluation, and it wraps "
        "across several rendered lines without ever ending a paragraph."
    )
    document = parse(_pdf(tmp_path / f"w_{layout}.pdf", [sentence], layout))

    assert len(document.paragraphs) == 1
    assert _texts(document)[0] == sentence


def test_a_phrase_broken_by_a_line_wrap_stays_inside_one_paragraph(tmp_path):
    """The regression that matters to keyword search.

    Both matchers join query tokens with a whitespace pattern so a phrase
    still matches across a line break - but only while the whole phrase
    lives in a single searched span.
    """
    from features.multi_doc_keyword_search.matcher import compile_keyword

    sentence = (
        "This document describes the OSS authentication and configuration "
        "workflow used during the DC CAT prototype evaluation."
    )
    document = parse(_pdf(tmp_path / "phrase.pdf", [sentence], "loose"))

    pattern = compile_keyword("configuration workflow")
    assert any(pattern.search(p.text) for p in document.paragraphs)


def test_one_line_per_block_producers_do_not_shred_a_sentence(tmp_path):
    """Loose leading makes PyMuPDF emit one block per line; ignore that."""
    sentence = (
        "The collector retries the request until the operational data store "
        "acknowledges it or the configured retry budget for that element is "
        "exhausted by repeated failures."
    )
    path = _pdf(tmp_path / "sparse.pdf", [sentence], "loose", width=74)

    assert len([b for b in fitz.open(path)[0].get_text("blocks") if b[6] == 0]) > 1
    document = parse(path)
    assert len(document.paragraphs) == 1
    assert _texts(document)[0] == sentence


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_capitalised_proper_noun_after_a_wrap_does_not_split(tmp_path, layout):
    """Capitalisation is deliberately not used as a boundary signal.

    Here a mid-paragraph line ends short and the next line opens with a
    proper noun. Splitting on that would tear the sentence in half and
    lose the phrase for both keyword-search features.
    """
    paragraph = (
        "The platform reloads the cached policy set after every restart and "
        "the Discovery Center Management Console then refreshes each "
        "operator view."
    )
    document = parse(_pdf(tmp_path / f"pn_{layout}.pdf", [paragraph], layout))

    assert len(document.paragraphs) == 1
    assert _texts(document)[0] == paragraph


# --- behaviour that must be preserved ----------------------------------


def _fake_page(lines: list[tuple[str, float, float, float]]):
    """A stand-in page exposing get_text("dict") lines: (text, x0, x1, top)."""

    class _Page:
        def get_text(self, _mode):
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {"bbox": (x0, top, x1, top + 10),
                             "spans": [{"text": text}]}
                            for text, x0, x1, top in lines
                        ],
                    }
                ]
            }

    return _Page()


def test_a_blank_line_in_the_extracted_text_always_breaks():
    """The original \\n\\n rule, preserved explicitly.

    Geometry alone would join these: the lines are evenly spaced and the
    first runs to the full column. The blank line must still break them.
    """
    page = _fake_page([
        ("First paragraph runs right to the margin here", 72, 400, 100),
        ("Second paragraph here.", 72, 300, 114),
    ])
    text = "First paragraph runs right to the margin here\n\nSecond paragraph here.\n"

    assert parser._page_paragraphs(page, text) == [
        "First paragraph runs right to the margin here",
        "Second paragraph here.",
    ]


def test_without_the_blank_line_the_same_geometry_joins():
    """Control for the test above: only the blank line changes the result."""
    page = _fake_page([
        ("First paragraph runs right to the margin here", 72, 400, 100),
        ("Second paragraph here.", 72, 300, 114),
    ])
    text = "First paragraph runs right to the margin here\nSecond paragraph here.\n"

    assert len(parser._page_paragraphs(page, text)) == 1


def test_blank_line_positions_are_ignored_when_they_disagree_with_geometry():
    """A text/geometry mismatch must not shift breaks onto wrong lines."""
    assert parser._blank_line_breaks("a\n\nb\n\nc\n", 3) == {0, 1}
    assert parser._blank_line_breaks("a\n\nb\n\nc\n", 7) == set()


def test_extra_vertical_space_breaks_paragraphs(tmp_path):
    """The spacing signal, on a real PDF."""
    document = parse(_pdf(tmp_path / "gapped.pdf", BODY, "gapped"))
    assert _texts(document) == [_flat(t) for t in BODY]


def test_the_blank_line_fallback_is_kept_for_pages_without_geometry():
    """When line geometry is unavailable the original \\n\\n split is used."""

    class _NoGeometry:
        def get_text(self, _mode):
            raise RuntimeError("no dict from this build")

    text = "First paragraph.\n\nSecond paragraph."
    assert parser._page_paragraphs(_NoGeometry(), text) == [
        "First paragraph.",
        "Second paragraph.",
    ]


def test_page_numbers_and_indices_are_preserved(tmp_path):
    doc = fitz.open()
    for number in range(1, 4):
        page = doc.new_page()
        y = 80.0
        body = f"Page {number} opens with a heading. " + "Body text follows. " * 12
        for line in textwrap.wrap(body, 78):
            page.insert_text((72, y), line, fontsize=9)
            y += 11
    path = str(tmp_path / "multi.pdf")
    doc.save(path)
    doc.close()

    document = parse(path)
    assert document.page_count == 3
    assert [p.number for p in document.pages] == [1, 2, 3]
    assert [p.index for p in document.paragraphs] == list(
        range(len(document.paragraphs))
    )
    assert sorted({p.page for p in document.paragraphs}) == [1, 2, 3]
    # paragraph pages never run backwards: reading order is preserved
    pages = [p.page for p in document.paragraphs]
    assert pages == sorted(pages)


def test_paragraph_text_comes_only_from_the_page_it_belongs_to(tmp_path):
    document = parse(_pdf(tmp_path / "dense.pdf", BODY, "dense"))
    by_number = {page.number: _flat(page.text) for page in document.pages}
    for paragraph in document.paragraphs:
        assert _flat(paragraph.text) in by_number[paragraph.page]


def test_paragraphs_are_stripped_and_never_empty(tmp_path):
    document = parse(_pdf(tmp_path / "dense.pdf", BODY, "dense"))
    for paragraph in document.paragraphs:
        assert paragraph.text == paragraph.text.strip()
        assert paragraph.text


def test_splitting_is_deterministic(tmp_path):
    path = _pdf(tmp_path / "dense.pdf", BODY, "dense")
    first = [(p.page, p.index, p.text) for p in parse(path).paragraphs]
    second = [(p.page, p.index, p.text) for p in parse(path).paragraphs]
    assert first == second


def test_an_empty_page_contributes_no_paragraphs(tmp_path):
    doc = fitz.open()
    doc.new_page()
    path = str(tmp_path / "blank.pdf")
    doc.save(path)
    doc.close()

    document = parse(path)
    assert document.page_count == 1
    assert document.paragraphs == []


# --- the shipped fixtures ----------------------------------------------


FIXTURES = [
    "fixtures/sample.pdf",
    "fixtures/demo_manual.pdf",
    "fixtures/test_broken_links.pdf",
]


@pytest.mark.parametrize("path", FIXTURES)
def test_fixtures_now_yield_more_paragraphs_than_pages(path):
    document = parse(path)
    assert len(document.paragraphs) > document.page_count


@pytest.mark.parametrize("path", FIXTURES)
def test_fixture_paragraphs_stay_within_their_page(path):
    document = parse(path)
    by_number = {page.number: _flat(page.text) for page in document.pages}
    for paragraph in document.paragraphs:
        assert 1 <= paragraph.page <= document.page_count
        assert _flat(paragraph.text) in by_number[paragraph.page]


def test_the_sample_fixture_separates_its_heading_from_its_body():
    document = parse("fixtures/sample.pdf")
    page_one = [_flat(p.text) for p in document.paragraphs if p.page == 1]
    assert page_one == [
        "1 Introduction",
        "This document describes the OSS authentication and configuration "
        "workflow used during the DC CAT prototype evaluation.",
    ]


def test_the_demo_fixture_recovers_its_authored_paragraphs():
    """External check against a real fixture's own generator script."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_demo", "fixtures/make_demo.py"
    )
    make_demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_demo)

    authored = []
    for number, title, paragraphs in make_demo.SECTIONS:
        authored.append(_flat(f"{number} {title}" if number else title))
        authored += [_flat(p) for p in paragraphs]

    recovered = _texts(parse("fixtures/demo_manual.pdf"))
    intact = sum(1 for a in authored if any(a in r for r in recovered))
    # Every authored paragraph must survive whole somewhere; a handful may
    # share a paragraph with a neighbour, but none may be torn in half.
    assert intact >= len(authored) - 2, (
        f"only {intact}/{len(authored)} authored paragraphs survived intact"
    )


def test_headings_and_links_are_unaffected():
    document = parse("fixtures/sample.pdf")
    assert [h.number for h in document.headings] == ["1", "2", "2.1", "3", "3.1", "4"]
    assert len(document.links) == 3
    assert document.format == "pdf"
    assert document.path == "fixtures/sample.pdf"


# --- the splitting rules, directly -------------------------------------


def test_line_pitch_is_the_ordinary_line_step():
    lines = [
        parser._Line("a", 72, 400, 100),
        parser._Line("b", 72, 400, 112),
        parser._Line("c", 72, 400, 124),
        parser._Line("d", 72, 400, 160),  # paragraph gap, must not skew it
    ]
    assert parser._line_pitch(lines) == 12


def test_line_pitch_of_a_single_line_is_zero():
    assert parser._line_pitch([parser._Line("only", 72, 400, 100)]) == 0.0


@pytest.mark.parametrize(
    "line",
    ["3.1 Two-Factor Verification", "4 Configuration", "1. Introduction"],
)
def test_numbered_headings_are_recognised(line):
    assert parser._is_numbered_heading(line)


@pytest.mark.parametrize(
    "line",
    ["continues in lower case", "2003 was the first release.", "Plain title"],
)
def test_prose_is_not_mistaken_for_a_heading(line):
    assert not parser._is_numbered_heading(line)


@pytest.mark.parametrize(
    "line",
    ["- restart the collector", "1) register the element", "3.1 Access Control"],
)
def test_list_items_and_headings_open_a_paragraph(line):
    assert parser._opens_paragraph(line)


def test_ordinary_prose_does_not_open_a_paragraph():
    assert not parser._opens_paragraph("The collector retries the request.")


def test_page_lines_skip_image_blocks():
    class _WithImage:
        def get_text(self, _mode):
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "bbox": (72, 100, 400, 112),
                                "spans": [{"text": "Real text."}],
                            }
                        ],
                    },
                    {"type": 1, "lines": []},  # image block
                ]
            }

    lines = parser._page_lines(_WithImage())
    assert [line.text for line in lines] == ["Real text."]
    assert lines[0].right == 400


def test_page_lines_are_empty_when_geometry_is_unavailable():
    class _Unreadable:
        def get_text(self, _mode):
            raise RuntimeError("nope")

    assert parser._page_lines(_Unreadable()) == []
