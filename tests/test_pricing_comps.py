# tests/test_pricing_comps.py
"""Hand-written tests for select_comps — no test code was carried over from
the plan for this task, so these are pinned against a broken implementation
one at a time (see the report for the failures observed)."""
from sublease.pricing.comps import CompSet, select_comps
from sublease.profile.models import Place

ALWAYS = lambda user_hood, offer_hood: True
NEVER = lambda user_hood, offer_hood: False


def make_place(**overrides):
    fields = {"neighborhood": "East Village", "unit_type": "room", "bedrooms": 2}
    fields.update(overrides)
    return Place(**fields)


def offer(nightly_price=70.0, unit_type="room", neighborhood="East Village",
          bedrooms=2, **overrides):
    row = {"nightly_price": nightly_price, "unit_type": unit_type,
           "neighborhood": neighborhood, "bedrooms": bedrooms}
    row.update(overrides)
    return row


# -- dropping: nightly_price null ---------------------------------------

def test_offer_with_no_nightly_price_is_dropped_not_treated_as_zero():
    offers = [offer(nightly_price=None), offer(nightly_price=80.0)]
    result = select_comps(offers, make_place(), ALWAYS)
    assert result.count == 1
    assert result.dropped == 1
    assert result.median == 80.0


# -- dropping: unit type is a hard filter --------------------------------

def test_room_never_compared_against_whole_unit():
    offers = [offer(unit_type="whole_unit", nightly_price=200.0),
              offer(unit_type="room", nightly_price=70.0)]
    result = select_comps(offers, make_place(unit_type="room"), ALWAYS)
    assert result.count == 1
    assert result.comps[0]["nightly_price"] == 70.0
    assert result.dropped == 1


# -- dropping: neighborhood -----------------------------------------------

def test_offer_with_no_neighborhood_string_is_dropped_without_calling_matcher():
    calls = []

    def spy(user_hood, offer_hood):
        calls.append((user_hood, offer_hood))
        return True

    offers = [offer(neighborhood=None)]
    result = select_comps(offers, make_place(), spy)
    assert result.count == 0
    assert result.dropped == 1
    assert calls == []  # never even asked — nothing to judge


def test_neighborhood_matcher_false_drops_the_comp():
    offers = [offer(neighborhood="Astoria")]
    result = select_comps(offers, make_place(neighborhood="East Village"), NEVER)
    assert result.count == 0
    assert result.dropped == 1


def test_neighborhood_matcher_receives_place_and_offer_neighborhoods_in_order():
    seen = []

    def spy(user_hood, offer_hood):
        seen.append((user_hood, offer_hood))
        return True

    offers = [offer(neighborhood="E Village")]
    select_comps(offers, make_place(neighborhood="East Village"), spy)
    assert seen == [("East Village", "E Village")]


# -- ranking: bedrooms are soft, used to order not exclude -----------------

def test_bedroom_mismatch_never_excludes_only_reorders():
    offers = [offer(bedrooms=4, nightly_price=90.0),
              offer(bedrooms=2, nightly_price=70.0),
              offer(bedrooms=1, nightly_price=60.0)]
    result = select_comps(offers, make_place(bedrooms=2), ALWAYS)
    assert result.count == 3  # nothing excluded on bedroom count
    assert [c["bedrooms"] for c in result.comps] == [2, 1, 4]  # closest-first


def test_unknown_bedrooms_sort_after_every_known_value():
    offers = [offer(bedrooms=None, nightly_price=55.0),
              offer(bedrooms=5, nightly_price=90.0),  # |5-2| = 3, worst known
              offer(bedrooms=2, nightly_price=70.0)]
    result = select_comps(offers, make_place(bedrooms=2), ALWAYS)
    assert [c["bedrooms"] for c in result.comps] == [2, 5, None]


# -- median / low / high ----------------------------------------------------

def test_median_of_odd_sample():
    offers = [offer(nightly_price=p) for p in (50.0, 70.0, 90.0)]
    result = select_comps(offers, make_place(), ALWAYS)
    assert result.median == 70.0
    assert result.low == 50.0
    assert result.high == 90.0


def test_median_of_even_sample_is_the_average_of_the_middle_two():
    offers = [offer(nightly_price=p) for p in (50.0, 60.0, 80.0, 90.0)]
    result = select_comps(offers, make_place(), ALWAYS)
    assert result.median == 70.0  # (60 + 80) / 2


# -- thin flag ----------------------------------------------------------

def test_four_comps_is_thin_but_median_still_reported():
    offers = [offer(nightly_price=p) for p in (50.0, 60.0, 70.0, 80.0)]
    result = select_comps(offers, make_place(), ALWAYS)
    assert result.count == 4
    assert result.thin is True
    assert result.median == 65.0  # thin does not suppress the median


def test_five_comps_is_not_thin():
    offers = [offer(nightly_price=p) for p in (50.0, 60.0, 70.0, 80.0, 90.0)]
    result = select_comps(offers, make_place(), ALWAYS)
    assert result.count == 5
    assert result.thin is False


def test_zero_comps_is_thin_with_no_median():
    result = select_comps([], make_place(), ALWAYS)
    assert result.count == 0
    assert result.thin is True
    assert result.median is None
    assert result.low is None
    assert result.high is None


# -- dropped is a count, reported alongside comps, not folded into count --

def test_dropped_count_reflects_every_rejection_reason_combined():
    offers = [
        offer(nightly_price=None),               # dropped: no price
        offer(unit_type="whole_unit"),            # dropped: unit type
        offer(neighborhood=None),                 # dropped: no neighborhood
        offer(nightly_price=70.0),                # kept
    ]
    result = select_comps(offers, make_place(), ALWAYS)
    assert result.count == 1
    assert result.dropped == 3


def test_compset_is_a_frozen_value_object():
    result = select_comps([], make_place(), ALWAYS)
    assert isinstance(result, CompSet)
