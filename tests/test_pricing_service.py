"""Hand-written tests for `sublease.pricing.service.price_place` — no test
code was carried over from the plan for this task, so these are pinned
against a broken implementation one at a time.
"""
from datetime import date

import pytest

from sublease.errors import ProviderError
from sublease.pricing.service import price_place
from sublease.profile.models import Place, Window
from sublease.store.db import connect, migrate
from sublease.store.repositories import ExtractionRepo, OfferRepo, PostRepo
from tests.fakes import FakeProvider

TODAY = date(2026, 8, 11)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


def make_place(**overrides):
    fields = {"neighborhood": "East Village", "unit_type": "room", "bedrooms": 2}
    fields.update(overrides)
    return Place(**fields)


WINDOW = Window(start=date(2026, 8, 18), end=date(2026, 9, 8))  # 22 nights


def seed_non_seeker_post(conn, post_id: str, text: str) -> None:
    """A post extraction has already decided is NOT seeking — pass 3's input."""
    PostRepo(conn).upsert_many([{"id": post_id, "text": text}])
    ExtractionRepo(conn).save_many([{
        "post_id": post_id, "is_seeking": False, "start_date": None,
        "end_date": None, "date_text": None, "budget": None,
        "confidence": "low", "model": None, "error": None,
    }])


# --- mode selection ----------------------------------------------------------

def test_estimate_mode_when_no_usable_offers_exist(conn):
    """The database is empty (the `init`, first-run case) — no non-seeker
    posts at all, so there is nothing to extract and no comps possible."""
    provider = FakeProvider(responses={"EstimateResult:East Village": {
        "low": 60.0, "high": 90.0, "note": "typical for a shared room here"}})
    result = price_place(conn, make_place(), WINDOW, provider, TODAY)
    assert result.mode == "estimate"
    assert result.estimate_low == 60.0
    assert result.estimate_high == 90.0
    assert result.comp_set is None


def test_comps_mode_when_a_usable_offer_already_exists(conn):
    """An offer row is already in the database (as if a previous `sublease
    run` had populated it) — comps mode must be chosen over estimate mode,
    with no non-seeker posts pending extraction."""
    PostRepo(conn).upsert_many([{"id": "fbpost:1", "text": "$70/night room in EV"}])
    OfferRepo(conn).save_many([{
        "post_id": "fbpost:1", "price_amount": 70, "price_unit": "night",
        "nightly_price": 70.0, "currency": "USD", "neighborhood": "East Village",
        "unit_type": "room", "bedrooms": 2, "bath": "shared", "furnished": True,
        "start_date": "2026-08-15", "end_date": "2026-09-05", "model": "fake",
        "error": None,
    }])
    provider = FakeProvider(responses={"NeighborhoodBatch:East Village": {
        "results": [{"neighborhood": "East Village", "relation": "same"}]}})
    result = price_place(conn, make_place(), WINDOW, provider, TODAY)
    assert result.mode == "comps"
    assert result.comp_set.count == 1
    assert result.comp_set.median == 70.0


# --- the offer-extraction sync (pass 3 wired into the service) --------------

def test_price_place_extracts_offers_from_pending_non_seeker_posts(conn):
    """price_place is the production caller of run_offer_extraction +
    OfferRepo.save_many — nothing else in the codebase wires pass 3 in. A
    non-seeker post with no offer row yet must get one before comps are
    selected."""
    seed_non_seeker_post(conn, "fbpost:1", "$80/night room in East Village")
    provider = FakeProvider(responses={
        "OfferBatch:fbpost:1": {"results": [
            {"id": "fbpost:1", "price_amount": "80", "price_unit": "night",
             "neighborhood": "East Village", "unit_type": "room", "bedrooms": 2}]},
        "NeighborhoodBatch:East Village": {"results": [
            {"neighborhood": "East Village", "relation": "same"}]},
    })
    result = price_place(conn, make_place(), WINDOW, provider, TODAY)
    assert OfferRepo(conn).done_ids() == {"fbpost:1"}
    assert result.mode == "comps"
    assert result.comp_set.count == 1


def test_a_post_with_an_offer_row_already_saved_is_never_re_extracted(conn):
    seed_non_seeker_post(conn, "fbpost:1", "$80/night room")
    OfferRepo(conn).save_many([{
        "post_id": "fbpost:1", "price_amount": 80, "price_unit": "night",
        "nightly_price": 80.0, "currency": "USD", "neighborhood": "East Village",
        "unit_type": "room", "bedrooms": 2, "bath": "shared", "furnished": True,
        "start_date": None, "end_date": None, "model": "fake", "error": None,
    }])
    # No canned OfferBatch response registered — a re-extraction attempt
    # would raise "no canned response matched this prompt".
    provider = FakeProvider(responses={"NeighborhoodBatch:East Village": {
        "results": [{"neighborhood": "East Village", "relation": "same"}]}})
    result = price_place(conn, make_place(), WINDOW, provider, TODAY)
    assert result.mode == "comps"
    # Only the neighborhood-matching call happened — the offer-extraction
    # prompt for "fbpost:1" was never sent, because no canned response was
    # registered for it and FakeProvider would have raised had it tried.
    assert len(provider.calls) == 1


# --- neighborhood matching: same vs adjacent, model-decided, no alias table --

def test_adjacent_comps_are_included_and_labelled_not_mixed_in_silently(conn):
    PostRepo(conn).upsert_many([
        {"id": "fbpost:1", "text": "$70/night, East Village"},
        {"id": "fbpost:2", "text": "$90/night, Alphabet City"},
    ])
    OfferRepo(conn).save_many([
        {"post_id": "fbpost:1", "price_amount": 70, "price_unit": "night",
         "nightly_price": 70.0, "currency": "USD", "neighborhood": "East Village",
         "unit_type": "room", "bedrooms": 2, "bath": "shared", "furnished": True,
         "start_date": None, "end_date": None, "model": "fake", "error": None},
        {"post_id": "fbpost:2", "price_amount": 90, "price_unit": "night",
         "nightly_price": 90.0, "currency": "USD", "neighborhood": "Alphabet City",
         "unit_type": "room", "bedrooms": 2, "bath": "shared", "furnished": True,
         "start_date": None, "end_date": None, "model": "fake", "error": None},
    ])
    provider = FakeProvider(responses={"NeighborhoodBatch:Alphabet City": {
        "results": [
            {"neighborhood": "Alphabet City", "relation": "adjacent"},
            {"neighborhood": "East Village", "relation": "same"},
        ]}})
    result = price_place(conn, make_place(), WINDOW, provider, TODAY)
    assert result.comp_set.count == 2
    assert result.neighborhood_relations["Alphabet City"] == "adjacent"
    assert result.neighborhood_relations["East Village"] == "same"


def test_a_different_neighborhood_is_excluded_from_the_comp_set(conn):
    PostRepo(conn).upsert_many([{"id": "fbpost:1", "text": "$70/night, Astoria"}])
    OfferRepo(conn).save_many([{
        "post_id": "fbpost:1", "price_amount": 70, "price_unit": "night",
        "nightly_price": 70.0, "currency": "USD", "neighborhood": "Astoria",
        "unit_type": "room", "bedrooms": 2, "bath": "shared", "furnished": True,
        "start_date": None, "end_date": None, "model": "fake", "error": None,
    }])
    provider = FakeProvider(responses={"NeighborhoodBatch:Astoria": {
        "results": [{"neighborhood": "Astoria", "relation": "different"}]}})
    result = price_place(conn, make_place(), WINDOW, provider, TODAY)
    assert result.mode == "comps"          # data existed — still comps mode
    assert result.comp_set.count == 0      # just none of it matched
    assert result.comp_set.dropped == 1


# --- provider failure propagates, isn't swallowed here -----------------------

def test_a_provider_error_during_estimation_propagates(conn):
    provider = FakeProvider(fail_on={"You estimate"})
    with pytest.raises(ProviderError):
        price_place(conn, make_place(), WINDOW, provider, TODAY)


def test_a_provider_error_during_neighborhood_matching_propagates(conn):
    PostRepo(conn).upsert_many([{"id": "fbpost:1", "text": "$70/night, EV"}])
    OfferRepo(conn).save_many([{
        "post_id": "fbpost:1", "price_amount": 70, "price_unit": "night",
        "nightly_price": 70.0, "currency": "USD", "neighborhood": "EV",
        "unit_type": "room", "bedrooms": 2, "bath": "shared", "furnished": True,
        "start_date": None, "end_date": None, "model": "fake", "error": None,
    }])
    provider = FakeProvider(fail_on={"You match neighborhood names"})
    with pytest.raises(ProviderError):
        price_place(conn, make_place(), WINDOW, provider, TODAY)
