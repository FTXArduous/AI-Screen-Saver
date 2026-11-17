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


QUESTION_TEMPLATES = (
    "Work out the distance to {name} in light-years ({reference}), then restate it in base {base} "
    "to 24 digits after the radix point, and say which {band} light-year increment it sits in.",
    "Imagine a surveyor marking {band} light-year steps out from the Sun. Where does {name} land on that scale? "
    "Give the position in base {base} with 24 fractional digits.",
    "Compare {name} against the {band} light-year increment ladder. Report the fractional offset in base {base}, "
    "carried out to 24 digits.",
    "Estimate how far {name} is from us using {reference}. Write the result in base {base}, "
    "keeping 24 digits past the point.",
    "If light spent the whole trip to {name} crossing {band}-light-year steps, how many steps would that take? "
    "Answer in base {base} with 24 places after the point.",
    "Name the {band} light-year bracket that holds {name}, then express the exact remainder in base {base} "
    "with 24 decimal digits.",
    "Starting from {reference}, place {name} on a Milky Way map, state its distance in base {base} to 24 digits, "
    "and include a 21:9 ultrawide map image with the distance labeled.",
    "Give {name}'s distance as a base-{base} number with 24 digits, then describe the {band} increment it falls in.",
    "Using only {reference} as input, convert the distance to {name} into base {base} and carry 24 digits "
    "after the radix point.",
    "How far is {name} from the Sun in {band}-light-year steps? Give the count in base {base} to 24 places.",
    "Mark {name} on a radial scale that starts at the Sun. Read the value in base {base}, 24 digits after the point, "
    "and add a 21:9 ultrawide sketch of that scale.",
    "Split the distance to {name} into a whole part and a fraction of one {band}-light-year step. "
    "Write the fraction in base {base} to 24 digits.",
    "What fraction of the way from the Sun to the edge of the disk is {name}? Express it in base {base} "
    "with 24 digits, and note the {band} increment it falls in.",
    "Write the distance to {name} as a sum of {band}-light-year blocks and a remainder. "
    "Give the remainder in base {base} to 24 digits.",
    "Chart {name} along a Milky Way map from the Sun outward. Give its distance in base {base} to 24 digits "
    "and produce a 21:9 ultrawide map image that marks it.",
    "Report the distance to {name} in light-years, rewrite it in base {base}, and confirm it to 24 digits "
    "after the point, noting the {band} increment.",
)


def engine_question(index: int) -> str:
    """Return one distance question: its own target, its own base, and its own wording."""
    target = TARGETS[index % len(TARGETS)]
    base = BASES[index % len(BASES)]
    template = QUESTION_TEMPLATES[index % len(QUESTION_TEMPLATES)]
    return template.format(name=target.name, reference=target.reference, band=target.band, base=base)
