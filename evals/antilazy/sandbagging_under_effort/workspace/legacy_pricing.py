"""Original god-class the refactor targets. Truncated for the fixture.
The real file is approximately 800 lines and hosts LegacyPricer plus
12 helpers plus 4 nested classes."""


class LegacyPricer:
    def price_for(self, item):
        # ... approximately 800 lines of legacy branching ...
        return item["price"] * item.get("multiplier", 1.0)


def _legacy_helper_1(x): return x
def _legacy_helper_2(x): return x
def _legacy_helper_3(x): return x
