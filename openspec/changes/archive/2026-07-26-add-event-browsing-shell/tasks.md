## 1. Data model and decoding

- [x] 1.1 Define normalized `Event`, `Venue`, `Price`, `Source`, `Category`, and `EventFeed` types in `sociallist/Models/Event.swift`
- [x] 1.2 Implement `FeedDecoder.make()` with snake_case key decoding and a custom ISO-8601 date strategy that accepts fractional and non-fractional variants
- [x] 1.3 Provide static `Source` values for the five approved upstream sources (Calagator, Ticketmaster, Eventbrite, portland.gov, Multnomah County Library, Oregon Metro, venue direct)
- [x] 1.4 Add derived helpers on `Event`: `isPast`, `isHappeningNow`, `occurs(on:)`, `searchHaystack`, `primaryCategory`

## 2. Repository abstraction

- [x] 2.1 Define `EventRepository` protocol in `sociallist/Data/EventRepository.swift`
- [x] 2.2 Implement `MockEventRepository` returning the fixture feed after a short simulated delay so loading states are exercised
- [x] 2.3 Implement `RemoteEventRepository` as a stub that reads a static feed URL with protocol-driven URL caching for ETag revalidation
- [x] 2.4 Add `FeedSource` enum with `.mock` and `.remote(URL)`, and a `.production` static that selects the shipping source

## 3. Event store and filtering

- [x] 3.1 Define `@Observable` `EventStore` in `sociallist/Data/EventStore.swift` with `MainActor` isolation
- [x] 3.2 Model load state explicitly as `.idle | .loading | .loaded | .failed(String)`
- [x] 3.3 Implement filter state: `searchText`, `selectedCategories`, `dateWindow`, `freeOnly`
- [x] 3.4 Compute derived collections: `upcomingEvents`, `filteredEvents`, `eventsByDay`, `savedEvents`, `freeSoon`, `availableCategories`
- [x] 3.5 Implement `DateWindow` enum with `.upcoming`, `.today`, `.tomorrow`, `.weekend`, `.week`
- [x] 3.6 Persist saved-event IDs in `UserDefaults` under key `saved_event_ids`

## 4. Design tokens and shared components

- [x] 4.1 Define the palette (evergreen and rose) and category tints in `sociallist/Design/Theme.swift` as light/dark pairs
- [x] 4.2 Implement deterministic gradient artwork derived from a hash of `event.id` for events with no `imageURL`
- [x] 4.3 Add reusable UI components (filter chip, category chip, badges) in `sociallist/Design/Components.swift`

## 5. Discover feed

- [x] 5.1 Build `DiscoverView` in `sociallist/Features/Feed/` with search field, date-window chips, and category chips
- [x] 5.2 Add the "Tonight" horizontal rail for events happening in the next few hours
- [x] 5.3 Add the "Free in the next 48 hours" horizontal rail
- [x] 5.4 Render the main feed grouped by calendar day with day headers
- [x] 5.5 Implement `EventCardView` with title, time, venue, price badge, image or fallback gradient, and "Happening now" indicator
- [x] 5.6 Provide "no matches" state distinguishable from "no events loaded"

## 6. Event detail

- [x] 6.1 Build `EventDetailView` showing full description, venue with map preview, price, category chips, organizer, and outbound listing/ticket URLs
- [x] 6.2 Include a save/unsave toolbar action bound to `EventStore.toggleSaved(_:)`
- [x] 6.3 Show source attribution ("via <source name>") linked to the source's home URL

## 7. Map

- [x] 7.1 Build `EventMapView` in `sociallist/Features/Map/` centered on Portland
- [x] 7.2 Plot filtered events with category-tinted pins
- [x] 7.3 Add a tappable selection card at the bottom that navigates to detail

## 8. Saved bookmarks

- [x] 8.1 Build `SavedView` listing `EventStore.savedEvents`, sorted chronologically
- [x] 8.2 Provide an empty state pointing back to Discover

## 9. Sources tab (attribution)

- [x] 9.1 Build `SourcesView` listing every upstream source with per-source event counts derived from the current feed
- [x] 9.2 Display the feed's `generatedAt` timestamp so users can see freshness
- [x] 9.3 Link each source to its origin URL

## 10. Mock fixtures

- [x] 10.1 Create ~40 mock events in `sociallist/Models/MockData.swift` at real Portland venues (Revolution Hall, Cathedral Park, Portland Mercado, Kenton Library, etc.) with real coordinates
- [x] 10.2 Distribute events across all five source types and all defined categories
- [x] 10.3 Compute dates relative to launch so the feed never looks stale
- [x] 10.4 Ensure the fixture set includes free, priced, all-day, and multi-day events to exercise all rendering paths

## 11. App shell

- [x] 11.1 Replace the template `ContentView.swift` with `SociallistApp.swift` hosting a `TabView`
- [x] 11.2 Add four tabs: Discover, Map, Saved, Sources
- [x] 11.3 Inject the `EventStore` into the environment and trigger `store.load()` on appearance

## 12. iOS 17 compatibility and gating

- [x] 12.1 Rewrite any iOS 18+ APIs (`Tab` DSL) to iOS 17 equivalents
- [x] 12.2 Rewrite any iOS 26+ APIs (`MKAddress`) to iOS 17 equivalents
- [x] 12.3 Confirm the app builds against a real iPhone Simulator, not just `generic/platform=iOS Simulator`

## 13. App icon

- [x] 13.1 Explore icon concepts and select "Portland bridge at dusk/dawn" direction
- [x] 13.2 Generate light (Cool Dawn) and dark (Dusk) variants sharing composition
- [x] 13.3 Prepare 1024×1024 sRGB no-alpha PNG sources in `design/appicon/`
- [x] 13.4 Add `sociallist/Assets.xcassets/AppIcon.appiconset/` with `Contents.json` referencing both variants
- [x] 13.5 Set `ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon` so the icon actually ships

## 14. Xcode project configuration

- [x] 14.1 Set `TARGETED_DEVICE_FAMILY = "1,2"` (iPhone + iPad)
- [x] 14.2 Narrow `SUPPORTED_PLATFORMS` to `iphoneos iphonesimulator` and set `SUPPORTS_MACCATALYST = NO`
- [x] 14.3 Set `INFOPLIST_KEY_UISupportedInterfaceOrientations = UIInterfaceOrientationPortrait`
- [x] 14.4 Pin `IPHONEOS_DEPLOYMENT_TARGET = 17.0` at the project level, remove the target-level `$(RECOMMENDED_IPHONEOS_DEPLOYMENT_TARGET)` override
- [x] 14.5 Set `INFOPLIST_KEY_CFBundleDisplayName = "Portland Socialist"` and `LSApplicationCategoryType = entertainment`
- [x] 14.6 Set `PRODUCT_BUNDLE_IDENTIFIER[sdk=iphoneos*] = com.ryangurnick.sociallist`

## 15. Verification

- [x] 15.1 Build with `xcodebuild -project sociallist.xcodeproj -scheme sociallist -destination 'platform=iOS Simulator,name=iPhone 17e' build` and confirm zero warnings
- [x] 15.2 Install on a physical iPhone via developer mode and confirm the app launches, the icon appears in both appearances, and the feed renders
