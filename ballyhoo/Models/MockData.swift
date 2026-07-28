import Foundation

/// Stand-in for the static JSON feed the pipeline will publish.
///
/// Venues and coordinates are real so map and neighborhood filtering behave
/// realistically. Dates are relative to launch so the feed never looks stale.
enum MockData {

    static let feed = EventFeed(generatedAt: .now, events: events)

    static var events: [Event] { builders.map { $0() } }

    // MARK: Venues

    private enum Venues {
        static let revolutionHall = Venue(name: "Revolution Hall", address: "1300 SE Stark St", neighborhood: "Buckman", latitude: 45.5192, longitude: -122.6537)
        static let dougFir = Venue(name: "Doug Fir Lounge", address: "830 E Burnside St", neighborhood: "Central Eastside", latitude: 45.5230, longitude: -122.6577)
        static let mississippiStudios = Venue(name: "Mississippi Studios", address: "3939 N Mississippi Ave", neighborhood: "Boise", latitude: 45.5528, longitude: -122.6757)
        static let holocene = Venue(name: "Holocene", address: "1001 SE Morrison St", neighborhood: "Central Eastside", latitude: 45.5175, longitude: -122.6580)
        static let crystalBallroom = Venue(name: "Crystal Ballroom", address: "1332 W Burnside St", neighborhood: "West End", latitude: 45.5225, longitude: -122.6845)
        static let roseland = Venue(name: "Roseland Theater", address: "8 NW 6th Ave", neighborhood: "Old Town", latitude: 45.5254, longitude: -122.6748)
        static let aladdin = Venue(name: "Aladdin Theater", address: "3017 SE Milwaukie Ave", neighborhood: "Brooklyn", latitude: 45.4970, longitude: -122.6540)
        static let wonderBallroom = Venue(name: "Wonder Ballroom", address: "128 NE Russell St", neighborhood: "Eliot", latitude: 45.5378, longitude: -122.6620)
        static let modaCenter = Venue(name: "Moda Center", address: "1 N Center Ct St", neighborhood: "Lloyd District", latitude: 45.5316, longitude: -122.6668)
        static let keller = Venue(name: "Keller Auditorium", address: "222 SW Clay St", neighborhood: "Downtown", latitude: 45.5122, longitude: -122.6810)
        static let schnitzer = Venue(name: "Arlene Schnitzer Concert Hall", address: "1037 SW Broadway", neighborhood: "Downtown", latitude: 45.5170, longitude: -122.6819)
        static let omsi = Venue(name: "OMSI", address: "1945 SE Water Ave", neighborhood: "Central Eastside", latitude: 45.5083, longitude: -122.6656)
        static let artMuseum = Venue(name: "Portland Art Museum", address: "1219 SW Park Ave", neighborhood: "Downtown", latitude: 45.5162, longitude: -122.6837)
        static let powells = Venue(name: "Powell's City of Books", address: "1005 W Burnside St", neighborhood: "Pearl District", latitude: 45.5232, longitude: -122.6814)
        static let centralLibrary = Venue(name: "Central Library", address: "801 SW 10th Ave", neighborhood: "Downtown", latitude: 45.5220, longitude: -122.6829)
        static let hollywoodLibrary = Venue(name: "Hollywood Library", address: "4040 NE Tillamook St", neighborhood: "Hollywood", latitude: 45.5352, longitude: -122.6215)
        static let kentonLibrary = Venue(name: "Kenton Library", address: "8226 N Denver Ave", neighborhood: "Kenton", latitude: 45.5790, longitude: -122.6890)
        static let midlandLibrary = Venue(name: "Midland Library", address: "805 SE 122nd Ave", neighborhood: "Hazelwood", latitude: 45.5150, longitude: -122.5390)
        static let pioneerSquare = Venue(name: "Pioneer Courthouse Square", address: "701 SW 6th Ave", neighborhood: "Downtown", latitude: 45.5188, longitude: -122.6793)
        static let saturdayMarket = Venue(name: "Portland Saturday Market", address: "2 SW Naito Pkwy", neighborhood: "Old Town", latitude: 45.5228, longitude: -122.6707)
        static let laurelhurstTheater = Venue(name: "Laurelhurst Theater", address: "2735 E Burnside St", neighborhood: "Laurelhurst", latitude: 45.5228, longitude: -122.6370)
        static let hollywoodTheatre = Venue(name: "Hollywood Theatre", address: "4122 NE Sandy Blvd", neighborhood: "Hollywood", latitude: 45.5352, longitude: -122.6244)
        static let providencePark = Venue(name: "Providence Park", address: "1844 SW Morrison St", neighborhood: "Goose Hollow", latitude: 45.5215, longitude: -122.6914)
        static let washingtonPark = Venue(name: "Washington Park", address: "4033 SW Canyon Rd", neighborhood: "Washington Park", latitude: 45.5124, longitude: -122.7160)
        static let forestPark = Venue(name: "Forest Park — Lower Macleay", address: "2960 NW Upshur St", neighborhood: "Northwest District", latitude: 45.5370, longitude: -122.7130)
        static let cathedralPark = Venue(name: "Cathedral Park", address: "N Edison St & Pittsburg Ave", neighborhood: "St. Johns", latitude: 45.5875, longitude: -122.7597)
        static let luckyLab = Venue(name: "Lucky Labrador Beer Hall", address: "1945 NW Quimby St", neighborhood: "Slabtown", latitude: 45.5350, longitude: -122.6900)
        static let kennedySchool = Venue(name: "McMenamins Kennedy School", address: "5736 NE 33rd Ave", neighborhood: "Concordia", latitude: 45.5628, longitude: -122.6295)
        static let mercado = Venue(name: "Portland Mercado", address: "7238 SE Foster Rd", neighborhood: "Foster-Powell", latitude: 45.4924, longitude: -122.5885)
        static let lanSu = Venue(name: "Lan Su Chinese Garden", address: "239 NW Everett St", neighborhood: "Old Town", latitude: 45.5258, longitude: -122.6730)
        static let japaneseGarden = Venue(name: "Portland Japanese Garden", address: "611 SW Kingston Ave", neighborhood: "Washington Park", latitude: 45.5190, longitude: -122.7080)
        static let albertaRose = Venue(name: "Alberta Rose Theatre", address: "3000 NE Alberta St", neighborhood: "Concordia", latitude: 45.5590, longitude: -122.6320)
        static let albertaStreet = Venue(name: "NE Alberta Street", address: "NE Alberta St & 15th Ave", neighborhood: "Alberta Arts", latitude: 45.5590, longitude: -122.6470)
        static let cityHall = Venue(name: "Portland City Hall", address: "1221 SW 4th Ave", neighborhood: "Downtown", latitude: 45.5150, longitude: -122.6790)
        static let psu = Venue(name: "PSU Park Blocks", address: "1825 SW Broadway", neighborhood: "University District", latitude: 45.5115, longitude: -122.6835)
        static let polarisHall = Venue(name: "Polaris Hall", address: "635 N Killingsworth Ct", neighborhood: "Piedmont", latitude: 45.5625, longitude: -122.6710)
        static let sellwoodPark = Venue(name: "Sellwood Riverfront Park", address: "SE Spokane St & Oaks Pkwy", neighborhood: "Sellwood", latitude: 45.4720, longitude: -122.6660)
        static let leachGarden = Venue(name: "Leach Botanical Garden", address: "6704 SE 122nd Ave", neighborhood: "Lents", latitude: 45.4740, longitude: -122.5380)
    }

    // MARK: Builders

    /// Closures rather than values so every launch recomputes dates from `now`.
    private static let builders: [() -> Event] = [
        {
            Event(
                id: "ticketmaster:pdx-thunder-1",
                title: "Portland Trail Blazers vs. Golden State Warriors",
                summary: "Regular season matchup at the Moda Center. Doors open 90 minutes before tip-off.",
                start: at(hour: 19, dayOffset: 0),
                end: at(hour: 22, dayOffset: 0),
                venue: Venues.modaCenter,
                categories: [.sports],
                price: .range(38, 320),
                url: URL(string: "https://www.ticketmaster.com"),
                ticketURL: URL(string: "https://www.ticketmaster.com"),
                organizer: "Portland Trail Blazers",
                source: .ticketmaster
            )
        },
        {
            Event(
                id: "venue:doug-fir-tonight",
                title: "Sun Atlas with Neighbors & Strangers",
                summary: "Hazy shoegaze from a Portland four-piece, plus support from two local openers. 21+.",
                start: at(hour: 21, dayOffset: 0),
                end: at(hour: 23, minute: 30, dayOffset: 0),
                venue: Venues.dougFir,
                categories: [.music, .nightlife],
                price: .from(18),
                url: URL(string: "https://www.dougfirlounge.com"),
                ticketURL: URL(string: "https://www.dougfirlounge.com"),
                organizer: "Doug Fir Lounge",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "calagator:pdx-rust-meetup",
                title: "PDX Rust: Embedded Systems Night",
                summary: "Two talks on embedded Rust, followed by open hacking. Beginners welcome — bring a laptop if you want to follow along.",
                start: at(hour: 18, dayOffset: 0),
                end: at(hour: 20, minute: 30, dayOffset: 0),
                venue: Venues.luckyLab,
                categories: [.tech, .community],
                price: .free,
                url: URL(string: "https://calagator.org"),
                organizer: "PDX Rust",
                source: .calagator
            )
        },
        {
            Event(
                id: "multcolib:storytime-kenton",
                title: "Family Storytime",
                summary: "Stories, songs, and rhymes for children up to age 6 and their grown-ups. Drop in, no registration.",
                start: at(hour: 10, minute: 30, dayOffset: 1),
                end: at(hour: 11, dayOffset: 1),
                venue: Venues.kentonLibrary,
                categories: [.family, .literary],
                price: .free,
                url: URL(string: "https://multcolib.org/events-classes"),
                organizer: "Multnomah County Library",
                source: .multcoLib
            )
        },
        {
            Event(
                id: "dopdx:foster-night-market",
                title: "Foster Night Market",
                summary: "Twenty rotating food carts, live cumbia, and a maker market in the Mercado courtyard. Family friendly until 9pm.",
                start: at(hour: 17, dayOffset: 1),
                end: at(hour: 22, dayOffset: 1),
                venue: Venues.mercado,
                categories: [.food, .market, .community],
                price: .free,
                url: URL(string: "https://dopdx.com"),
                organizer: "Portland Mercado",
                source: .dopdx
            )
        },
        {
            Event(
                id: "venue:mississippi-studios-1",
                title: "Blitzen Trapper — Hometown Run",
                summary: "Three nights of deep cuts and new material. This is night one.",
                start: at(hour: 20, dayOffset: 1),
                end: at(hour: 23, dayOffset: 1),
                venue: Venues.mississippiStudios,
                categories: [.music],
                price: .from(32),
                url: URL(string: "https://www.mississippistudios.com"),
                ticketURL: URL(string: "https://www.mississippistudios.com"),
                organizer: "Mississippi Studios",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "portland_gov:tree-stewards",
                title: "Neighborhood Tree Steward Work Party",
                summary: "Help mulch and water street trees in the Cully neighborhood. Tools, gloves, and coffee provided. No experience needed.",
                start: at(hour: 9, dayOffset: 2),
                end: at(hour: 12, dayOffset: 2),
                venue: Venues.albertaStreet,
                categories: [.outdoors, .community, .civic],
                price: .free,
                url: URL(string: "https://www.portland.gov/events"),
                organizer: "Portland Parks & Recreation",
                source: .portlandGov
            )
        },
        {
            Event(
                id: "venue:saturday-market",
                title: "Portland Saturday Market",
                summary: "The largest continuously operating outdoor arts and crafts market in the country. Over 250 vendors along the waterfront.",
                start: at(hour: 10, dayOffset: 2),
                end: at(hour: 17, dayOffset: 2),
                venue: Venues.saturdayMarket,
                categories: [.market, .arts, .food],
                price: .free,
                url: URL(string: "https://www.portlandsaturdaymarket.com"),
                organizer: "Portland Saturday Market",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "dopdx:alberta-last-thursday",
                title: "Last Thursday on Alberta",
                summary: "Fifteen blocks of street art, buskers, and pop-up vendors. Alberta closes to cars between 15th and 30th.",
                start: at(hour: 18, dayOffset: 2),
                end: at(hour: 21, minute: 30, dayOffset: 2),
                venue: Venues.albertaStreet,
                categories: [.arts, .community, .market],
                price: .free,
                url: URL(string: "https://dopdx.com"),
                organizer: "Alberta Main Street",
                source: .dopdx
            )
        },
        {
            Event(
                id: "venue:omsi-after-dark",
                title: "OMSI After Dark: Science of Fermentation",
                summary: "Adults-only evening at the museum with tastings, hands-on labs, and full access to the exhibit halls. 21+.",
                start: at(hour: 19, dayOffset: 2),
                end: at(hour: 23, dayOffset: 2),
                venue: Venues.omsi,
                categories: [.food, .community],
                price: .from(25),
                url: URL(string: "https://www.omsi.edu/events/"),
                ticketURL: URL(string: "https://www.omsi.edu/events/"),
                organizer: "OMSI",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "ticketmaster:schnitzer-symphony",
                title: "Oregon Symphony: Rachmaninoff & Sibelius",
                summary: "Piano Concerto No. 2 paired with Sibelius's Second Symphony.",
                start: at(hour: 19, minute: 30, dayOffset: 3),
                end: at(hour: 21, minute: 45, dayOffset: 3),
                venue: Venues.schnitzer,
                categories: [.music, .arts],
                price: .range(29, 145),
                url: URL(string: "https://www.ticketmaster.com"),
                ticketURL: URL(string: "https://www.ticketmaster.com"),
                organizer: "Oregon Symphony",
                source: .ticketmaster
            )
        },
        {
            Event(
                id: "venue:forest-park-hike",
                title: "Guided Forest Park Morning Hike",
                summary: "A four-mile naturalist-led loop from Lower Macleay up to the Stone House. Moderate pace, rain or shine.",
                start: at(hour: 9, dayOffset: 3),
                end: at(hour: 11, minute: 30, dayOffset: 3),
                venue: Venues.forestPark,
                categories: [.outdoors, .wellness],
                price: .free,
                url: URL(string: "https://www.forestparkconservancy.org"),
                organizer: "Forest Park Conservancy",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "calagator:pdx-python",
                title: "PDX Python Monthly",
                summary: "Lightning talks and a main session on async patterns. Pizza at 6, talks at 6:30.",
                start: at(hour: 18, dayOffset: 4),
                end: at(hour: 20, minute: 30, dayOffset: 4),
                venue: Venues.psu,
                categories: [.tech, .community],
                price: .free,
                url: URL(string: "https://calagator.org"),
                organizer: "PDX Python",
                source: .calagator
            )
        },
        {
            Event(
                id: "venue:hollywood-70mm",
                title: "70mm Print: Lawrence of Arabia",
                summary: "A rare full-length 70mm screening with a 15-minute intermission. Seating is general admission.",
                start: at(hour: 19, dayOffset: 4),
                end: at(hour: 23, dayOffset: 4),
                venue: Venues.hollywoodTheatre,
                categories: [.film, .arts],
                price: .from(14),
                url: URL(string: "https://hollywoodtheatre.org"),
                ticketURL: URL(string: "https://hollywoodtheatre.org"),
                organizer: "Hollywood Theatre",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "multcolib:tech-help",
                title: "Tech Help Drop-In",
                summary: "One-on-one help with phones, laptops, email, and online forms. First come, first served.",
                start: at(hour: 14, dayOffset: 4),
                end: at(hour: 16, dayOffset: 4),
                venue: Venues.hollywoodLibrary,
                categories: [.tech, .community],
                price: .free,
                url: URL(string: "https://multcolib.org/events-classes"),
                organizer: "Multnomah County Library",
                source: .multcoLib
            )
        },
        {
            Event(
                id: "portland_gov:budget-forum",
                title: "District 3 Community Budget Forum",
                summary: "City councilors take questions on the draft budget. Attend in person or join the livestream. Interpretation available on request.",
                start: at(hour: 18, minute: 30, dayOffset: 5),
                end: at(hour: 20, minute: 30, dayOffset: 5),
                venue: Venues.cityHall,
                categories: [.civic, .community],
                price: .free,
                url: URL(string: "https://www.portland.gov/events"),
                organizer: "City of Portland",
                source: .portlandGov
            )
        },
        {
            Event(
                id: "dopdx:pearl-gallery-walk",
                title: "First Thursday Gallery Walk",
                summary: "Twenty-plus Pearl District galleries stay open late with new openings and artist talks.",
                start: at(hour: 17, minute: 30, dayOffset: 5),
                end: at(hour: 21, dayOffset: 5),
                venue: Venues.powells,
                categories: [.arts, .community],
                price: .free,
                url: URL(string: "https://dopdx.com"),
                organizer: "Pearl District Arts Association",
                source: .dopdx
            )
        },
        {
            Event(
                id: "venue:powells-reading",
                title: "Author Reading: Mitchell S. Jackson",
                summary: "A reading and conversation, followed by an audience Q&A and signing. Seating opens 30 minutes early.",
                start: at(hour: 19, dayOffset: 5),
                end: at(hour: 20, minute: 30, dayOffset: 5),
                venue: Venues.powells,
                categories: [.literary, .arts],
                price: .free,
                url: URL(string: "https://www.powells.com/events"),
                organizer: "Powell's Books",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "ticketmaster:crystal-ballroom-1",
                title: "Khruangbin",
                summary: "All ages. The Crystal's floating dance floor is standing room only.",
                start: at(hour: 20, dayOffset: 6),
                end: at(hour: 23, dayOffset: 6),
                venue: Venues.crystalBallroom,
                categories: [.music, .nightlife],
                price: .range(45, 89),
                url: URL(string: "https://www.ticketmaster.com"),
                ticketURL: URL(string: "https://www.ticketmaster.com"),
                organizer: "McMenamins",
                source: .ticketmaster
            )
        },
        {
            Event(
                id: "venue:japanese-garden-moon",
                title: "Moonviewing at the Japanese Garden",
                summary: "Evening garden access with shakuhachi flute performances and tea service in the pavilion.",
                start: at(hour: 19, minute: 30, dayOffset: 6),
                end: at(hour: 22, dayOffset: 6),
                venue: Venues.japaneseGarden,
                categories: [.arts, .outdoors, .wellness],
                price: .from(29),
                url: URL(string: "https://japanesegarden.org"),
                ticketURL: URL(string: "https://japanesegarden.org"),
                organizer: "Portland Japanese Garden",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "venue:cathedral-park-jazz",
                title: "Cathedral Park Jazz Festival",
                summary: "The longest-running free jazz festival west of the Mississippi. Three days under the St. Johns Bridge.",
                start: at(hour: 12, dayOffset: 7),
                end: at(hour: 21, dayOffset: 9),
                venue: Venues.cathedralPark,
                categories: [.music, .community, .outdoors],
                price: .free,
                url: URL(string: "https://www.jazzoregon.org"),
                organizer: "Jazz Society of Oregon",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "dopdx:sellwood-swap",
                title: "Sellwood Bike Swap & Repair Clinic",
                summary: "Buy, sell, or trade used bikes and parts. Free basic tune-ups from volunteer mechanics all afternoon.",
                start: at(hour: 11, dayOffset: 7),
                end: at(hour: 16, dayOffset: 7),
                venue: Venues.sellwoodPark,
                categories: [.community, .outdoors, .market],
                price: .free,
                url: URL(string: "https://dopdx.com"),
                organizer: "Sellwood Cycle Repair",
                source: .dopdx
            )
        },
        {
            Event(
                id: "venue:kennedy-school-soak",
                title: "Soaking Pool Live Music: Anna Tivel",
                summary: "Acoustic set poolside at the Kennedy School. Soaking pool admission included with ticket.",
                start: at(hour: 19, dayOffset: 8),
                end: at(hour: 21, dayOffset: 8),
                venue: Venues.kennedySchool,
                categories: [.music, .nightlife],
                price: .from(22),
                url: URL(string: "https://www.mcmenamins.com"),
                ticketURL: URL(string: "https://www.mcmenamins.com"),
                organizer: "McMenamins",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "oregon_metro:nature-restoration",
                title: "Volunteer Restoration Day at Leach Garden",
                summary: "Remove invasive ivy and plant natives along the creek. Ages 12+. Gloves and tools provided.",
                start: at(hour: 9, dayOffset: 8),
                end: at(hour: 13, dayOffset: 8),
                venue: Venues.leachGarden,
                categories: [.outdoors, .community],
                price: .free,
                url: URL(string: "https://www.oregonmetro.gov/events"),
                organizer: "Oregon Metro",
                source: .oregonMetro
            )
        },
        {
            Event(
                id: "venue:lan-su-tea",
                title: "Tea Tasting in the Tower of Cosmic Reflections",
                summary: "A guided tasting of four Chinese teas in the garden's teahouse. Limited to 20 guests.",
                start: at(hour: 14, dayOffset: 9),
                end: at(hour: 15, minute: 30, dayOffset: 9),
                venue: Venues.lanSu,
                categories: [.food, .arts, .wellness],
                price: .from(35),
                url: URL(string: "https://lansugarden.org"),
                ticketURL: URL(string: "https://lansugarden.org"),
                organizer: "Lan Su Chinese Garden",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "ticketmaster:keller-broadway",
                title: "Hadestown",
                summary: "The Tony-winning musical, on tour. Runs through Sunday.",
                start: at(hour: 19, minute: 30, dayOffset: 9),
                end: at(hour: 22, dayOffset: 9),
                venue: Venues.keller,
                categories: [.arts, .music],
                price: .range(49, 199),
                url: URL(string: "https://www.ticketmaster.com"),
                ticketURL: URL(string: "https://www.ticketmaster.com"),
                organizer: "Broadway in Portland",
                source: .ticketmaster
            )
        },
        {
            Event(
                id: "calagator:design-week-kickoff",
                title: "Portland Design Week Kickoff",
                summary: "Opening night party and portfolio show. Free, but RSVP fills up fast.",
                start: at(hour: 18, dayOffset: 10),
                end: at(hour: 21, dayOffset: 10),
                venue: Venues.revolutionHall,
                categories: [.arts, .tech, .community],
                price: .free,
                url: URL(string: "https://calagator.org"),
                organizer: "Design Week Portland",
                source: .calagator
            )
        },
        {
            Event(
                id: "venue:holocene-dance",
                title: "Bubble Wrap: 2000s Dance Party",
                summary: "Resident DJs playing nothing but 2000s pop and R&B. 21+, doors at 9.",
                start: at(hour: 21, dayOffset: 10),
                end: at(hour: 2, dayOffset: 11),
                venue: Venues.holocene,
                categories: [.nightlife, .music],
                price: .from(12),
                url: URL(string: "https://holocene.org/events/"),
                ticketURL: URL(string: "https://holocene.org/events/"),
                organizer: "Holocene",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "dopdx:pdx-vegan-fest",
                title: "Portland Vegan Beer & Food Festival",
                summary: "Sixty breweries and thirty food vendors, all plant-based. Ticket includes a tasting glass and eight pours.",
                start: at(hour: 12, dayOffset: 11),
                end: at(hour: 20, dayOffset: 11),
                venue: Venues.pioneerSquare,
                categories: [.food, .market, .community],
                price: .range(35, 60),
                url: URL(string: "https://dopdx.com"),
                ticketURL: URL(string: "https://www.veganbeerfest.com"),
                organizer: "Vegan Beer & Food Fest",
                source: .dopdx
            )
        },
        {
            Event(
                id: "venue:aladdin-comedy",
                title: "Live Wire! Radio Show Taping",
                summary: "A live taping of the public radio variety show, with musical guests and interviews.",
                start: at(hour: 19, minute: 30, dayOffset: 12),
                end: at(hour: 21, minute: 30, dayOffset: 12),
                venue: Venues.aladdin,
                categories: [.arts, .community],
                price: .range(28, 45),
                url: URL(string: "https://aladdin-theater.com"),
                ticketURL: URL(string: "https://aladdin-theater.com"),
                organizer: "Live Wire! Radio",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "multcolib:sewing-group",
                title: "International Women's Sewing Group",
                summary: "A weekly drop-in group sharing machines, patterns, and conversation. All skill levels and languages welcome.",
                start: at(hour: 13, dayOffset: 12),
                end: at(hour: 15, dayOffset: 12),
                venue: Venues.midlandLibrary,
                categories: [.community, .arts],
                price: .free,
                url: URL(string: "https://multcolib.org/events-classes"),
                organizer: "Multnomah County Library",
                source: .multcoLib
            )
        },
        {
            Event(
                id: "ticketmaster:providence-timbers",
                title: "Portland Timbers vs. Seattle Sounders",
                summary: "Cascadia Cup rivalry match. Timbers Army in the north end.",
                start: at(hour: 19, minute: 30, dayOffset: 13),
                end: at(hour: 21, minute: 30, dayOffset: 13),
                venue: Venues.providencePark,
                categories: [.sports],
                price: .range(42, 210),
                url: URL(string: "https://www.ticketmaster.com"),
                ticketURL: URL(string: "https://www.ticketmaster.com"),
                organizer: "Portland Timbers",
                source: .ticketmaster
            )
        },
        {
            Event(
                id: "venue:art-museum-late",
                title: "Museum Late: Contemporary Northwest",
                summary: "After-hours access to the new Northwest galleries with a cash bar and live DJ sets.",
                start: at(hour: 18, dayOffset: 14),
                end: at(hour: 21, dayOffset: 14),
                venue: Venues.artMuseum,
                categories: [.arts, .nightlife],
                price: .from(20),
                url: URL(string: "https://portlandartmuseum.org"),
                ticketURL: URL(string: "https://portlandartmuseum.org"),
                organizer: "Portland Art Museum",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "venue:polaris-folk",
                title: "Fiddle & Song Circle",
                summary: "An open acoustic session — bring an instrument or just listen. Tunes shared by ear.",
                start: at(hour: 19, dayOffset: 15),
                end: at(hour: 21, minute: 30, dayOffset: 15),
                venue: Venues.polarisHall,
                categories: [.music, .community],
                price: .from(10),
                url: URL(string: "https://polarishall.com"),
                organizer: "Polaris Hall",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "venue:washington-park-summer",
                title: "Washington Park Summer Concert",
                summary: "Free outdoor concert on the lawn. Bring a blanket; food carts on site from 5pm.",
                start: at(hour: 18, dayOffset: 16),
                end: at(hour: 20, minute: 30, dayOffset: 16),
                venue: Venues.washingtonPark,
                categories: [.music, .outdoors, .family],
                price: .free,
                url: URL(string: "https://www.explorewashingtonpark.org"),
                organizer: "Explore Washington Park",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "venue:wonder-ballroom-1",
                title: "Y La Bamba with Edna Vazquez",
                summary: "Portland's own Y La Bamba headlining a hometown show. All ages.",
                start: at(hour: 20, dayOffset: 17),
                end: at(hour: 23, dayOffset: 17),
                venue: Venues.wonderBallroom,
                categories: [.music],
                price: .from(28),
                url: URL(string: "https://www.wonderballroom.com"),
                ticketURL: URL(string: "https://www.wonderballroom.com"),
                organizer: "Wonder Ballroom",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "venue:laurelhurst-repertory",
                title: "Repertory Night: Paris, Texas",
                summary: "Wim Wenders on 35mm, with beer and pizza service during the film.",
                start: at(hour: 20, minute: 30, dayOffset: 18),
                end: at(hour: 23, dayOffset: 18),
                venue: Venues.laurelhurstTheater,
                categories: [.film],
                price: .from(10),
                url: URL(string: "https://laurelhursttheater.com"),
                organizer: "Laurelhurst Theater",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "calagator:pdx-web-a11y",
                title: "Portland Web Accessibility Meetup",
                summary: "A practical walkthrough of screen reader testing, with time to audit your own site afterward.",
                start: at(hour: 18, minute: 30, dayOffset: 19),
                end: at(hour: 20, minute: 30, dayOffset: 19),
                venue: Venues.centralLibrary,
                categories: [.tech, .community],
                price: .free,
                url: URL(string: "https://calagator.org"),
                organizer: "PDX Web Accessibility",
                source: .calagator
            )
        },
        {
            Event(
                id: "dopdx:st-johns-parade",
                title: "St. Johns Bizarre & Parade",
                summary: "A neighborhood street festival with a parade, three music stages, and a hundred vendors along Lombard.",
                start: at(hour: 10, dayOffset: 20),
                end: at(hour: 20, dayOffset: 20),
                venue: Venues.cathedralPark,
                categories: [.community, .market, .music, .family],
                price: .free,
                url: URL(string: "https://dopdx.com"),
                organizer: "St. Johns Boosters",
                source: .dopdx
            )
        },
        {
            Event(
                id: "venue:alberta-rose-variety",
                title: "The Moth StorySLAM: Neighbors",
                summary: "Ten storytellers, five minutes each, no notes. Put your name in the hat at the door.",
                start: at(hour: 19, minute: 30, dayOffset: 21),
                end: at(hour: 21, minute: 30, dayOffset: 21),
                venue: Venues.albertaRose,
                categories: [.literary, .arts, .community],
                price: .from(18),
                url: URL(string: "https://albertarosetheatre.com"),
                ticketURL: URL(string: "https://albertarosetheatre.com"),
                organizer: "The Moth",
                source: .venueDirect
            )
        },
        {
            Event(
                id: "venue:roseland-hiphop",
                title: "Aminé — Portland Homecoming",
                summary: "One night only, with special guests to be announced.",
                start: at(hour: 20, dayOffset: 22),
                end: at(hour: 23, minute: 30, dayOffset: 22),
                venue: Venues.roseland,
                categories: [.music, .nightlife],
                price: .range(55, 120),
                url: URL(string: "https://www.roselandpdx.com"),
                ticketURL: URL(string: "https://www.roselandpdx.com"),
                organizer: "Roseland Theater",
                source: .venueDirect
            )
        }
    ]

    // MARK: Date helper

    private static func at(hour: Int, minute: Int = 0, dayOffset: Int) -> Date {
        let calendar = Calendar.current
        let day = calendar.date(byAdding: .day, value: dayOffset, to: .now) ?? .now
        return calendar.date(
            bySettingHour: hour,
            minute: minute,
            second: 0,
            of: day
        ) ?? day
    }
}
