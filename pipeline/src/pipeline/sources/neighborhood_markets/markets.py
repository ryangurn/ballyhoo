"""The markets this source covers, each encoded from its own website's sentence.

**Maintaining an entry.** When a run logs that a market's statement changed, open the
page in `statements`, copy the new sentence in verbatim, and re-derive `rules`, `days`,
`through` and `skipped` from it. Encode only what the sentence states: if it says
"every other Sunday" without saying which, that part is left out rather than guessed.

**`through`.** A sentence that names exact dates — "May 16th through October 24th
2026" — describes one season, so `through` is that season's last date and nothing after
it is published even if the page is never updated. A sentence that names only months
— "May through October" — is the operator's standing schedule, and is expanded every
year until the page changes.

Seasons in `WeeklyRule` are year-less month/day pairs (see `common.recurrence`), so
`through` is what keeps a dated sentence from repeating into a year it never mentioned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from ...common.recurrence import MonthDay, Season, WeeklyRule

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)


@dataclass(frozen=True)
class Statement:
    """A sentence that must still appear on `url` for the rules to be trusted."""

    url: str
    text: str


@dataclass(frozen=True)
class MarketDay:
    """A single dated market day the operator lists explicitly."""

    day: date
    opens: time
    closes: time | None
    title: str | None = None


@dataclass(frozen=True)
class Market:
    slug: str
    name: str
    statements: tuple[Statement, ...]
    # The venue publishes under the market's own name, as every market source does, so
    # cross-source dedup can match it; the place itself goes in the address.
    address: str
    city: str
    rules: tuple[WeeklyRule, ...] = ()
    days: tuple[MarketDay, ...] = ()
    through: date | None = None
    skipped: frozenset[date] = field(default_factory=frozenset)

    @property
    def listing_url(self) -> str:
        return self.statements[0].url


def weekly(weekday: int, opens: time, closes: time, start: MonthDay, end: MonthDay, *, ordinals=()) -> WeeklyRule:
    return WeeklyRule(
        weekday=weekday,
        start_time=opens,
        end_time=closes,
        season=Season(start, end),
        ordinals=frozenset(ordinals),
    )


def year_round(weekday: int, opens: time, closes: time) -> WeeklyRule:
    return WeeklyRule(weekday=weekday, start_time=opens, end_time=closes)


MARKETS: tuple[Market, ...] = (
    # --- Portland neighborhoods -------------------------------------------------------
    Market(
        slug="montavilla",
        name="Montavilla Farmers Market",
        statements=(
            Statement(
                "https://www.montavillamarket.org/",
                "May–December 20: Every Sunday January–April: Every Other Sunday "
                "SE Stark & 76th [7700 SE Stark St.] 10am–2pm",
            ),
        ),
        address="7700 SE Stark St, Portland, OR 97215",
        city="Portland",
        # "Every Other Sunday" in winter does not say which Sundays, so only the
        # weekly season is encoded.
        rules=(weekly(SUNDAY, time(10), time(14), MonthDay(5, 1), MonthDay(12, 20)),),
        through=date(2026, 12, 20),
    ),
    Market(
        slug="woodstock",
        name="Woodstock Farmers Market",
        statements=(
            Statement("https://woodstockmarketpdx.com/", "Join us every Sunday from 10am - 2pm through October 25th!"),
            Statement(
                "https://woodstockmarketpdx.com/",
                "Open Sundays, June - October + November's Harvest Market 10am - 2pm 4600 SE Woodstock Blvd",
            ),
        ),
        address="4600 SE Woodstock Blvd, Portland, OR 97206",
        city="Portland",
        # The November Harvest Market's date is not on the page.
        rules=(weekly(SUNDAY, time(10), time(14), MonthDay(6, 1), MonthDay(10, 25)),),
        through=date(2026, 10, 25),
    ),
    Market(
        slug="woodlawn",
        name="Woodlawn Farmers Market",
        statements=(
            Statement(
                "https://www.woodlawnfarmersmarket.org/",
                "Join us at the market every Saturday June 6th-October 24th 9am - 1pm",
            ),
        ),
        address="NE Dekum St & NE Durham Ave, Portland, OR 97211",
        city="Portland",
        # The winter market moves to Classic Foods with no day or hours stated.
        rules=(weekly(SATURDAY, time(9), time(13), MonthDay(6, 6), MonthDay(10, 24)),),
        through=date(2026, 10, 24),
    ),
    Market(
        slug="cully",
        name="Cully Farmers Market",
        statements=(
            Statement(
                "https://cullyfarmersmarket.com/",
                "EVERY THURSDAY 4pm - 8pm • MAY - SEPTEMBER 2026 • NE 42nd Ave. & NE Alberta St.",
            ),
        ),
        address="NE 42nd Ave & NE Alberta St, Portland, OR 97218",
        city="Portland",
        rules=(weekly(THURSDAY, time(16), time(20), MonthDay(5, 1), MonthDay(9, 30)),),
        through=date(2026, 9, 30),
    ),
    Market(
        slug="st-johns",
        name="St. Johns Farmers Market",
        statements=(
            Statement(
                "https://www.stjohnsopportunity.org/market-info",
                "Weekly on Saturdays - 9:00am – 2:00pm - May 2 - November 21, 2026",
            ),
            Statement(
                "https://www.stjohnsopportunity.org/market-info",
                "Holiday Market - 10:00am-2:00pm - Saturday, December 12, 2026",
            ),
        ),
        address="N Charleston Ave & N Central St, Portland, OR 97203",
        city="Portland",
        rules=(weekly(SATURDAY, time(9), time(14), MonthDay(5, 2), MonthDay(11, 21)),),
        days=(MarketDay(date(2026, 12, 12), time(10), time(14), title="St. Johns Holiday Market"),),
        through=date(2026, 12, 12),
    ),
    Market(
        slug="sellwood-moreland",
        name="Sellwood Moreland Farmers Market",
        statements=(
            Statement(
                "https://www.morelandfarmersmarket.org/time-place",
                "Every Saturday 10:00AM to 2:00PM May 16th through October 24th 2026",
            ),
        ),
        address="SE Claybourne St between SE Milwaukie Ave and SE 17th Ave, Portland, OR 97202",
        city="Portland",
        rules=(weekly(SATURDAY, time(10), time(14), MonthDay(5, 16), MonthDay(10, 24)),),
        through=date(2026, 10, 24),
    ),
    Market(
        slug="rocky-butte",
        name="Rocky Butte Farmers Market",
        statements=(
            Statement(
                "https://www.rockybuttemarket.com/",
                "May through October • Every Saturday from 9AM - 1PM • NE Siskiyou & NE 80th Ave",
            ),
        ),
        address="NE Siskiyou St & NE 80th Ave, Portland, OR 97213",
        city="Portland",
        rules=(weekly(SATURDAY, time(9), time(13), MonthDay(5, 1), MonthDay(10, 31)),),
    ),
    Market(
        slug="peoples",
        name="People's Farmers Market",
        statements=(
            Statement(
                "https://www.peoples.coop/farmers-market",
                "People's Farmers' Market is Every Wednesday at the Co-op Market Hours: 2-7pm 3029 SE 21st Avenue",
            ),
        ),
        address="People's Food Co-op, 3029 SE 21st Ave, Portland, OR 97202",
        city="Portland",
        rules=(year_round(WEDNESDAY, time(14), time(19)),),
    ),
    Market(
        slug="come-thru",
        name="Come Thru Market",
        statements=(Statement("https://www.comethrupdx.org/", "Open 1st and 3rd Mondays, June - October, 3-7pm."),),
        address="2766 NE Martin Luther King Jr Blvd, Portland, OR 97212",
        city="Portland",
        rules=(weekly(MONDAY, time(15), time(19), MonthDay(6, 1), MonthDay(10, 31), ordinals=(1, 3)),),
    ),
    Market(
        slug="ohsu",
        name="OHSU Farmers Market",
        statements=(
            Statement(
                "https://www.ohsu.edu/farmers-market",
                "We are excited for 2026! Our hours are 10 a.m. to 2 p.m. every Tuesday June through September.",
            ),
        ),
        address="OHSU Auditorium courtyard, 3286 SW Research Dr, Portland, OR 97239",
        city="Portland",
        rules=(weekly(TUESDAY, time(10), time(14), MonthDay(6, 1), MonthDay(9, 30)),),
        through=date(2026, 9, 30),
    ),
    Market(
        slug="south-waterfront",
        name="South Waterfront Farmers Market",
        statements=(
            Statement(
                "https://www.southwaterfront.com/farmers-market-about",
                "Stop by every Thursday, June through October for our summer season! NEW HOURS: 12:00 pm - 5:00 pm",
            ),
        ),
        address="Elizabeth Caruthers Park, 3508 S Moody Ave, Portland, OR 97239",
        city="Portland",
        rules=(weekly(THURSDAY, time(12), time(17), MonthDay(6, 1), MonthDay(10, 31)),),
    ),
    Market(
        slug="hillsdale",
        name="Hillsdale Farmers Market",
        statements=(
            Statement(
                "https://www.hillsdalefarmersmarket.com/",
                "Market hours: 9am-1pm every sunday April-Thanksgiving Twice monthly Dec-Mar",
            ),
            Statement(
                "https://www.hillsdalefarmersmarket.com/visit",
                "Our last weekly market of the 2026-27 season will be November 22. Specific winter market dates "
                "for the 2026-27 season are: December 6 & 20 January 10 & 24 February 7 & 21 March 7 & 21",
            ),
        ),
        address="Rieke Elementary School, 1405 SW Vermont St, Portland, OR 97219",
        city="Portland",
        rules=(weekly(SUNDAY, time(9), time(13), MonthDay(4, 1), MonthDay(11, 22)),),
        days=tuple(
            MarketDay(day, time(9), time(13))
            for day in (
                date(2026, 12, 6),
                date(2026, 12, 20),
                date(2027, 1, 10),
                date(2027, 1, 24),
                date(2027, 2, 7),
                date(2027, 2, 21),
                date(2027, 3, 7),
                date(2027, 3, 21),
            )
        ),
        through=date(2027, 3, 21),
    ),
    # --- East county ------------------------------------------------------------------
    Market(
        slug="gresham",
        name="Gresham Farmers Market",
        statements=(
            Statement(
                "https://www.greshamfarmersmarket.com/",
                "Center for the Arts Plaza NE 3rd st. and NE Hood ave. Every Saturday May through October "
                "8:30am - 2:00pm",
            ),
        ),
        address="Center for the Arts Plaza, NE 3rd St & NE Hood Ave, Gresham, OR 97030",
        city="Gresham",
        rules=(weekly(SATURDAY, time(8, 30), time(14), MonthDay(5, 1), MonthDay(10, 31)),),
    ),
    # --- West side --------------------------------------------------------------------
    Market(
        slug="beaverton",
        name="Beaverton Farmers Market",
        statements=(
            # Wix splits "April" across two spans and pads the text with zero-width
            # spaces; the comparison ignores both.
            Statement(
                "https://www.beavertonfarmersmarket.com/form-map",
                "2026 MARKET HOURS Every Saturday February - March 10:00 AM-1:30 PM April - November 21 "
                "8:30 AM- 1:30 PM",
            ),
        ),
        address="12375 SW 5th St, Beaverton, OR 97005",
        city="Beaverton",
        rules=(
            weekly(SATURDAY, time(8, 30), time(13, 30), MonthDay(4, 1), MonthDay(11, 21)),
            weekly(SATURDAY, time(10), time(13, 30), MonthDay(2, 1), MonthDay(3, 31)),
        ),
        through=date(2026, 11, 21),
    ),
    Market(
        slug="tigard",
        name="Tigard Farmers Market",
        statements=(
            Statement("https://www.tigardfarmersmarket.org/", "Sundays, May 3 – October 25, 2026 9:00 am – 1:30 pm"),
        ),
        address="Universal Plaza, 9100 SW Burnham St, Tigard, OR 97223",
        city="Tigard",
        rules=(weekly(SUNDAY, time(9), time(13, 30), MonthDay(5, 3), MonthDay(10, 25)),),
        through=date(2026, 10, 25),
    ),
    Market(
        slug="forest-grove",
        name="Forest Grove Farmers Market",
        statements=(
            Statement(
                "https://www.adelantefarmersmarket.org/",
                "Forest Grove Wednesdays, May 6 - October 28, 2026 4:00-8:00 PM",
            ),
        ),
        address="Main St between 21st Ave and Pacific Ave, Forest Grove, OR 97116",
        city="Forest Grove",
        rules=(weekly(WEDNESDAY, time(16), time(20), MonthDay(5, 6), MonthDay(10, 28)),),
        through=date(2026, 10, 28),
    ),
    Market(
        slug="cornelius",
        name="Cornelius Community Market",
        statements=(
            Statement(
                "https://www.adelantefarmersmarket.org/",
                "Cornelius Fridays, June 5 - August 28, 2026 4:00-8:00 PM",
            ),
        ),
        address="N 14th Ave near the Cornelius Public Library, Cornelius, OR 97113",
        city="Cornelius",
        rules=(weekly(FRIDAY, time(16), time(20), MonthDay(6, 5), MonthDay(8, 28)),),
        through=date(2026, 8, 28),
    ),
    # --- Clackamas County -------------------------------------------------------------
    Market(
        slug="milwaukie",
        name="Milwaukie Farmers Market",
        statements=(
            Statement(
                "https://milwaukiefarmersmarket.com/",
                "Every Sunday • May-October • 9:30AM-2PM DOWNTOWN MILWAUKIE",
            ),
        ),
        address="SE Main St & SE Harrison St, Milwaukie, OR 97222",
        city="Milwaukie",
        rules=(weekly(SUNDAY, time(9, 30), time(14), MonthDay(5, 1), MonthDay(10, 31)),),
    ),
    Market(
        slug="happy-valley",
        name="Happy Valley Farmers Market",
        statements=(
            Statement(
                "https://www.sunnysidefarmersmarkets.com/",
                "2027 Winter Season Indoor/Outdoor Market 10:00 a.m. – 2:00 p.m. January 9th and 23rd "
                "February 6th and 20th March 6th and 20th",
            ),
            Statement(
                "https://www.sunnysidefarmersmarkets.com/",
                "2026 Summer Season May 2nd – October 31st 9:00 a.m. – 2:00 p.m.",
            ),
            Statement(
                "https://www.sunnysidefarmersmarkets.com/",
                "2026 Harvest Market November 21st 9:00 a.m. – 2:00 p.m. "
                "13231 SE Sunnyside Rd, Clackamas, Oregon 97015",
            ),
        ),
        address="13231 SE Sunnyside Rd, Happy Valley, OR 97015",
        city="Happy Valley",
        rules=(weekly(SATURDAY, time(9), time(14), MonthDay(5, 2), MonthDay(10, 31)),),
        days=(
            MarketDay(date(2026, 11, 21), time(9), time(14), title="Happy Valley Harvest Market"),
            *(
                MarketDay(day, time(10), time(14), title="Happy Valley Winter Farmers Market")
                for day in (
                    date(2027, 1, 9),
                    date(2027, 1, 23),
                    date(2027, 2, 6),
                    date(2027, 2, 20),
                    date(2027, 3, 6),
                    date(2027, 3, 20),
                )
            ),
        ),
        through=date(2027, 3, 20),
    ),
    Market(
        slug="mount-hood",
        name="Mount Hood Farmers Market",
        statements=(
            Statement(
                "https://mounthoodfarmersmarket.org/",
                "Our market runs Fridays from May 15 to October 16, with no market on July 10.",
            ),
            Statement("https://mounthoodfarmersmarket.org/", "Market Hours Fridays 2pm - 7pm"),
        ),
        address="38600 Proctor Blvd, Sandy, OR 97055",
        city="Sandy",
        rules=(weekly(FRIDAY, time(14), time(19), MonthDay(5, 15), MonthDay(10, 16)),),
        through=date(2026, 10, 16),
        skipped=frozenset({date(2026, 7, 10)}),
    ),
    # --- Clark County, WA -------------------------------------------------------------
    Market(
        slug="camas",
        name="Camas Farmers Market",
        statements=(
            Statement(
                "https://camasfarmersmarket.org/event-details/",
                "The Camas Farmer’s Market runs from 3pm-7pm every Wednesday from June 3rd to September 30th, 2026 "
                "in Historic Downtown Camas",
            ),
        ),
        address="314 NE Birch St, Camas, WA 98607",
        city="Camas",
        rules=(weekly(WEDNESDAY, time(15), time(19), MonthDay(6, 3), MonthDay(9, 30)),),
        through=date(2026, 9, 30),
    ),
)
