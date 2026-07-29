import XCTest

/// Drives the app through the five screens that go on the App Store listing.
///
/// Run by `bundle exec fastlane screenshots`, not as part of a normal test
/// pass — it is a capture script, not a correctness check.
///
/// The app is launched with `-UITestMockData` so it reads `MockData` instead of
/// the published feed. The feed is whatever Portland happens to be doing that
/// morning, which makes a capture run unrepeatable and, on a quiet Tuesday in
/// February, unflattering.
///
/// Every step asserts. A run that quietly skipped a screen would leave a gap in
/// the upload that nobody notices until App Store Connect rejects it.
///
/// Isolation follows Xcode's own UI test template — `@MainActor` on the test
/// method and nothing on the class — with one addition. `XCTestCase`'s
/// initialisers are nonisolated, so a target built with
/// `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` cannot compile a subclass that
/// inherits that default. Saying `nonisolated` here fixes the isolation of the
/// class rather than leaving it to a build setting nobody has chosen yet.
/// Type-checks under Swift 5, Swift 6, and Swift 6 with main-actor defaults.
nonisolated final class ScreenshotUITests: XCTestCase {

    /// Generous, because a cold simulator under `xcodebuild test` is nothing
    /// like a warm one and the cost of being wrong is a whole failed run.
    private static let timeout: TimeInterval = 30

    @MainActor
    func testCaptureAppStoreScreenshots() throws {
        continueAfterFailure = false

        let app = XCUIApplication()
        setupSnapshot(app)
        app.launchArguments += ["-UITestMockData"]
        app.launch()

        captureDiscover(app)
        captureEventDetail(app)
        captureFreeFilter(app)
        captureMap(app)
        captureSaved(app)
    }

    // MARK: Screens

    /// The hero shot: editorial rails above the day-sectioned feed.
    @MainActor
    private func captureDiscover(_ app: XCUIApplication) {
        XCTAssertTrue(
            firstEventRow(app).waitForExistence(timeout: Self.timeout),
            "The feed never rendered an event row. Is the app launching with -UITestMockData?"
        )
        snapshot("01-Discover")
    }

    @MainActor
    private func captureEventDetail(_ app: XCUIApplication) {
        firstEventRow(app).tap()

        // Every screen has a navigation bar; only the detail screen has a share
        // button in it, so that is what says the push actually landed.
        let share = app.navigationBars.buttons
            .matching(NSPredicate(format: "label CONTAINS[c] 'share'"))
            .firstMatch

        XCTAssertTrue(
            share.waitForExistence(timeout: Self.timeout),
            "Tapping an event row did not open the detail screen."
        )
        snapshot("02-EventDetail")

        let back = app.navigationBars.buttons.element(boundBy: 0)
        XCTAssertTrue(back.waitForExistence(timeout: Self.timeout), "No back button on the detail screen.")
        back.tap()
    }

    /// Free events are what the app is for, so the filter earns a slot.
    @MainActor
    private func captureFreeFilter(_ app: XCUIApplication) {
        let free = app.buttons["Free"].firstMatch
        XCTAssertTrue(free.waitForExistence(timeout: Self.timeout), "No Free chip on Discover.")
        free.tap()

        // The clear button only exists while a filter is on, so it doubles as
        // proof the tap registered.
        let clear = app.buttons["Clear filters"].firstMatch
        XCTAssertTrue(
            clear.waitForExistence(timeout: Self.timeout),
            "The Free chip did not apply — Discover still shows no active filter."
        )
        snapshot("03-Free")

        clear.tap()
    }

    @MainActor
    private func captureMap(_ app: XCUIApplication) {
        openTab("Map", in: app)

        // The map's filter bar is only drawn once a feed has arrived, which
        // makes it a better readiness signal than the map itself: MapKit draws
        // its tiles whether or not there is anything to plot on them. The
        // Categories chip is the one control unique to this tab.
        XCTAssertTrue(
            app.buttons["Categories"].firstMatch.waitForExistence(timeout: Self.timeout),
            "The map never finished loading its events."
        )
        // Tiles keep arriving after the pins do, and a half-drawn basemap is an
        // obvious tell in a store screenshot.
        Thread.sleep(forTimeInterval: 4)
        snapshot("04-Map")
    }

    @MainActor
    private func captureSaved(_ app: XCUIApplication) {
        openTab("Discover", in: app)
        XCTAssertTrue(
            firstEventRow(app).waitForExistence(timeout: Self.timeout),
            "Lost the feed on the way back to Discover."
        )

        saveEvents(upTo: 3, in: app)

        openTab("Saved", in: app)
        XCTAssertTrue(
            buttons(labelled: "Remove from saved", in: app).firstMatch.waitForExistence(timeout: Self.timeout),
            "Saved is empty after bookmarking events."
        )
        snapshot("05-Saved")
    }

    // MARK: Helpers

    @MainActor
    private func firstEventRow(_ app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(identifier: "event-row").firstMatch
    }

    /// Simulators are reused between runs and the saved set lives in
    /// `UserDefaults`, so whatever the last run bookmarked is still bookmarked.
    /// Only unsaved rows are tapped — tapping every bookmark blindly would
    /// un-save them the second time round and photograph an empty tab.
    @MainActor
    private func saveEvents(upTo wanted: Int, in app: XCUIApplication) {
        var saved = buttons(labelled: "Remove from saved", in: app).count

        // Bounded rather than a `while`: a tap that never registers would
        // otherwise spin until the whole run times out with nothing to show.
        for _ in 0..<12 where saved < wanted {
            let unsaved = buttons(labelled: "Save event", in: app)
            guard unsaved.count > 0 else { break }
            unsaved.element(boundBy: 0).tap()
            saved += 1
        }

        XCTAssertGreaterThan(saved, 0, "Could not bookmark any event in the feed.")
    }

    /// Matched on the label rather than the identifier: these are SwiftUI
    /// buttons carrying an `accessibilityLabel` and no identifier of their own.
    @MainActor
    private func buttons(labelled label: String, in app: XCUIApplication) -> XCUIElementQuery {
        app.buttons.matching(NSPredicate(format: "label == %@", label))
    }

    /// A plain tab bar on iPhone and a floating one on iPad, and only the first
    /// is reachable through `tabBars`.
    @MainActor
    private func openTab(_ name: String, in app: XCUIApplication) {
        let inTabBar = app.tabBars.buttons[name]
        let tab = inTabBar.exists ? inTabBar : app.buttons[name].firstMatch

        XCTAssertTrue(tab.waitForExistence(timeout: Self.timeout), "No \(name) tab.")
        tab.tap()
    }
}
