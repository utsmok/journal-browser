"""observed_color: modal non-green oa_status of a work sample."""

from journal_browser.harvest.journal_oa import observed_color


def test_modal_color_ignores_green():
    assert observed_color(["gold"] * 18 + ["green"] * 2) == "gold"
    assert observed_color(["green"] * 20) == "green"
    assert observed_color([None, None]) is None
    assert observed_color([]) is None


def test_modal_color_ties_and_unknowns():
    # Tie -> fixed priority order, not sample order.
    assert observed_color(["diamond", "gold"]) == "gold"
    assert observed_color(["hybrid", "hybrid", "gold", "green"]) == "hybrid"
    # Unknown statuses resolve deterministically and never crash.
    assert observed_color(["weird", "weird", "gold"]) == "gold"
    assert observed_color(["weird"]) == "green"
