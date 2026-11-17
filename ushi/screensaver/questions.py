"""Milky Way distance questions. Each one asks ChatGPT for a distance written in a different number base."""

from typing import NamedTuple


class Target(NamedTuple):
    name: str
    reference: str
    band: str  # light-year increment the distance is placed in


# Sixteen distinct targets, from planets out to the Galaxy's edge, each paired with one number base below.
TARGETS = (
    Target("the Sun to Neptune", "about 30.07 AU, or 0.000475 light-years (orbital average)", "16"),
    Target("the Sun to Pluto", "about 39.5 AU, or 0.000625 light-years (orbital average)", "16"),
    Target("the Sun to the Oort Cloud's outer edge", "roughly 1 light-year (approximate estimate)", "16"),
    Target("the Sun to Proxima Centauri", "about 4.2465 light-years (Gaia DR3 parallax)", "16"),
    Target("the Sun to Alpha Centauri A", "about 4.37 light-years", "16"),
    Target("the Sun to Wolf 359", "about 7.86 light-years", "16"),
    Target("the Sun to Sirius A", "about 8.6 light-years", "16"),
    Target("the Sun to Epsilon Eridani", "about 10.5 light-years", "16"),
    Target("the Sun to Procyon", "about 11.46 light-years", "16"),
    Target("the Sun to Vega", "about 25 light-years", "120"),
    Target("the Sun to Arcturus", "about 36.7 light-years", "120"),
    Target("the Sun to Betelgeuse", "about 548 light-years (approximate estimate)", "120"),
    Target("the Sun to the Galactic Center", "about 26,670 light-years (8.18 kpc, GRAVITY Collaboration 2019)", "120"),
    Target("the Milky Way's disk diameter", "roughly 100,000 light-years (approximate published estimate)", "120"),
    Target("the Sun to the Large Magellanic Cloud", "about 163,000 light-years (approximate estimate)", "120"),
    Target("the Sun to the Andromeda Galaxy", "about 2.54 million light-years", "120"),
)

# One base per target, all distinct, so each question reads its digits in a different sequence.
BASES = (2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 20, 24)

QUESTION_COUNT = len(TARGETS)


def engine_question(index: int) -> str:
    """Return the distance question for one target, written in that target's number base."""
    target = TARGETS[index % len(TARGETS)]
    base = BASES[index % len(BASES)]
    return (
        f"Using the Milky Way as the reference, give the distance for {target.name}, "
        f"reference value {target.reference}, in light-years. "
        f"Place it in the {target.band} light-year increment and state where it falls within that increment. "
        f"Express the answer in base {base}: state the base first, give up to 24 digits after the radix point, "
        f"and keep the digit grouping consistent. "
        f"Also generate a 21:9 ultrawide image of a Milky Way map that shows {target.name}, "
        f"with the distance labeled on the map."
    )
