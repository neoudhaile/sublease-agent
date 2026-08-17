"""Hand-written tests for `sublease.cli.price.price_lines` — pure rendering,
data in, strings out, same pattern as `tests/test_cli_report.py`."""
from sublease.cli.price import price_lines
from sublease.pricing.comps import CompSet
from sublease.pricing.service import PricingResult
from sublease.profile.models import Place

PLACE = Place(neighborhood="East Village", unit_type="room", bedrooms=2)


def comp(nightly_price=70.0, neighborhood="East Village", bedrooms=2,
        furnished=True, start_date="2026-08-18", end_date="2026-09-08"):
    return {"nightly_price": nightly_price, "neighborhood": neighborhood,
            "bedrooms": bedrooms, "furnished": furnished,
            "start_date": start_date, "end_date": end_date}


# --- estimate mode is labelled everywhere -----------------------------------

def test_estimate_mode_labels_every_line_as_an_estimate():
    result = PricingResult(mode="estimate", place=PLACE, nights=22,
                           estimate_low=60.0, estimate_high=90.0,
                           estimate_note="seasonal demand is high in August")
    lines = price_lines(result)
    assert lines  # something was produced
    # The word must appear on the header AND the numbers line AND the note —
    # a user must never see a bare number with no "estimate" context.
    assert any("ESTIMATE" in line for line in lines)
    numbers_line = next(l for l in lines if "/night" in l)
    assert "ESTIMATE" in numbers_line
    assert "estimated" in numbers_line
    note_line = next(l for l in lines if "seasonal demand" in l)
    assert "ESTIMATE" in note_line


def test_estimate_mode_reports_the_total_for_the_users_window():
    result = PricingResult(mode="estimate", place=PLACE, nights=10,
                           estimate_low=50.0, estimate_high=100.0)
    lines = price_lines(result)
    numbers_line = next(l for l in lines if "/night" in l)
    assert "$500" in numbers_line
    assert "$1,000" in numbers_line
    assert "10 nights" in numbers_line


def test_estimate_mode_with_no_range_says_so_plainly():
    result = PricingResult(mode="estimate", place=PLACE, nights=10)
    lines = price_lines(result)
    assert any("unavailable" in line for line in lines)


# --- comps mode shows the comps, not just the number ------------------------

def test_comps_mode_lists_each_comp_individually():
    comp_set = CompSet(comps=[comp(70.0), comp(80.0), comp(90.0), comp(65.0), comp(75.0)],
                       median=75.0, low=65.0, high=90.0, count=5, dropped=1, thin=False)
    result = PricingResult(mode="comps", place=PLACE, nights=22, comp_set=comp_set,
                           neighborhood_relations={"East Village": "same"})
    lines = price_lines(result)
    assert sum(1 for line in lines if "/night" in line and "median" not in line) == 5
    assert any("median $75" in line for line in lines)
    assert any("range $65" in line and "$90" in line for line in lines)


def test_comps_mode_reports_the_total_for_the_users_window():
    comp_set = CompSet(comps=[comp(70.0)] * 5, median=70.0, low=70.0, high=70.0,
                       count=5, dropped=0, thin=False)
    result = PricingResult(mode="comps", place=PLACE, nights=22, comp_set=comp_set)
    lines = price_lines(result)
    summary = next(l for l in lines if "median" in l)
    assert "$1,540" in summary   # 70 * 22


def test_a_thin_sample_is_reported_as_thin_not_suppressed():
    comp_set = CompSet(comps=[comp(70.0), comp(80.0)], median=75.0, low=70.0,
                       high=80.0, count=2, dropped=0, thin=True)
    result = PricingResult(mode="comps", place=PLACE, nights=22, comp_set=comp_set)
    lines = price_lines(result)
    assert any("thin" in line.lower() for line in lines)
    # thin does NOT mean hidden — the median must still be there
    assert any("median $75" in line for line in lines)


def test_adjacent_comps_are_tagged_not_silently_mixed_in():
    comp_set = CompSet(
        comps=[comp(70.0, neighborhood="East Village"),
               comp(90.0, neighborhood="Alphabet City")],
        median=80.0, low=70.0, high=90.0, count=2, dropped=0, thin=True)
    result = PricingResult(
        mode="comps", place=PLACE, nights=22, comp_set=comp_set,
        neighborhood_relations={"East Village": "same", "Alphabet City": "adjacent"})
    lines = price_lines(result)
    adjacent_line = next(l for l in lines if "Alphabet City" in l)
    same_line = next(l for l in lines if l.strip().endswith("East Village"))
    assert "(adjacent)" in adjacent_line
    assert "(adjacent)" not in same_line
    assert "and nearby" in lines[0]   # the header signals a mixed sample


def test_zero_comps_says_so_and_reports_what_was_dropped():
    comp_set = CompSet(comps=[], median=None, low=None, high=None,
                       count=0, dropped=3, thin=True)
    result = PricingResult(mode="comps", place=PLACE, nights=22, comp_set=comp_set)
    lines = price_lines(result)
    assert len(lines) == 1
    assert "No comparable" in lines[0]
    assert "3" in lines[0]
