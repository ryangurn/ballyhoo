# Ballyhoo release automation

Builds, TestFlight and App Store uploads, and the App Store screenshot set.
Everything runs through Bundler so a release cut here and one cut in CI come out
of the same fastlane:

```sh
bundle install
bundle exec fastlane build
```

Always `bundle exec`. A Homebrew-installed fastlane on `PATH` is a different
version with different bugs, and it will happily run these lanes.

## The lanes

| Lane | What it does | Works today |
|---|---|---|
| `build` | Clean compile against the simulator SDK, no signing | yes |
| `screenshots` | Captures the five App Store screens on two devices | needs the test target |
| `beta` | Signed Release archive → TestFlight | needs an API key |
| `release` | Signed Release archive → App Store, binary only, no submission | needs an API key |
| `upload_screenshots` | Pushes `fastlane/screenshots` to the listing | needs an API key |

`build` is the one that needs nothing: no Apple account, no keychain, no
network. It is what a CI check would run and what to reach for when asking "does
this still compile".

`release` uploads the binary and stops. Submitting for review is a decision
about a listing being ready, not a step in a build, so it stays a deliberate
click in App Store Connect.

## Authentication

An App Store Connect API key, never an Apple ID. Apple ID authentication needs a
2FA code roughly whenever it feels like it, which is survivable at a desk and
fatal in a scheduled job — and the session token workaround expires on its own
schedule. A `.p8` key does not expire and never prompts.

### Getting one

You do not have a key yet. Once, in App Store Connect:

1. **Users and Access** → the **Integrations** tab.
2. **App Store Connect API** in the sidebar, then **Team Keys**.
3. **+**, name it something like `ballyhoo-release`, and give it the **App
   Manager** role. Developer is enough to upload a build but not to touch the
   listing, which `upload_screenshots` does.
4. **Generate**, then **Download API Key**.

   The `.p8` downloads exactly once. There is no second chance and no way to
   re-issue the same key — losing it means revoking it and starting over. Put it
   somewhere outside this repo, `~/.appstoreconnect/private_keys/` by
   convention, and back it up.
5. Copy the **Key ID** from the row, and the **Issuer ID** from the top of the
   page. Both are shown there permanently; only the key file is one-shot.

### Environment variables

| Variable | Where the value comes from | Needed by |
|---|---|---|
| `ASC_KEY_ID` | The Key ID column, next to the key you generated. Ten characters | `beta`, `release`, `upload_screenshots` |
| `ASC_ISSUER_ID` | Above the key table on the same page. A UUID, one per team | same |
| `ASC_KEY_PATH` | Wherever you saved the `.p8`. Absolute or `~`-relative | same |
| `ASC_TEAM_ID` | The Developer Portal team. Already in the project file as `DEVELOPMENT_TEAM`, so copy it from there | optional |
| `BALLYHOO_BUILD_NUMBER` | Whatever the next build number should be. See below | optional |

Locally, `fastlane/.env` is the least annoying place for them and is gitignored.
In CI, write the key secret to a file in a step and point `ASC_KEY_PATH` at it;
`*.p8` is gitignored precisely so nobody is ever one `git add -A` away from
publishing a signing key.

## Build numbers

App Store Connect rejects a build number it has already seen, and
`increment_build_number` works by rewriting `ballyhoo.xcodeproj/project.pbxproj`
— a generated edit to the project file, which is not a trade worth making for a
number. Pass it instead:

```sh
bundle exec fastlane beta build_number:7
```

That sets `CURRENT_PROJECT_VERSION` for the one build and leaves the project
alone. `BALLYHOO_BUILD_NUMBER` does the same thing from the environment, which
is the form CI wants. Without either, the build carries whatever the project
says, and the second upload of that number fails.

## Screenshots

Two device sizes, because App Store Connect scales every smaller display class
from the largest phone and the largest iPad. Uploading the rest changes nothing
on the listing.

| Slot | Device | What the simulator writes |
|---|---|---|
| iPhone 6.9" | iPhone 17 Pro Max | 1320 × 2868 |
| iPad 13" | iPad Air 13-inch (M4) | 2048 × 2732 |

Both figures were measured off the simulators rather than taken from a spec
sheet. Worth knowing if you were expecting to use the iPhone Air: it renders at
1260 × 2736, which is not one of the two sizes the 6.9" slot accepts, and a set
captured on it would be rejected. The `screenshots` lane creates the 17 Pro Max
simulator if the machine does not have one.

The app is launched with `-UITestMockData`, which makes it read
`ballyhoo/Models/MockData.swift` instead of the published feed. The feed is
whatever Portland is doing that morning — the screenshots would be
unrepeatable, and a quiet Tuesday in February would make the app look empty
through no fault of its own. The switch is behind `#if DEBUG` in
`BallyhooApp.swift`, so the branch is not in a release binary at all; that is
also why the Snapfile pins the capture to the Debug configuration.

No `frameit`. Framing puts the screenshot inside a drawn device bezel with a
caption above it, which costs real estate the feed uses well and adds a
`Framefile.json`, a font choice and a background to maintain. The screens are
dense and legible on their own.

The screens captured, in order: Discover, an event detail, Discover with the
Free filter on, the map, and Saved. Change the set in
`ballyhooUITests/ScreenshotUITests.swift`.

## One-time Xcode setup

`snapshot` drives the app from a UI test, and this project has no test target.
Creating one means editing `ballyhoo.xcodeproj/project.pbxproj`, which is
Xcode's job and nobody else's — so the sources are already written and waiting
in `ballyhooUITests/`, and the target has to be created by hand once.

The project already uses file-system-synchronized groups, so the two files on
disk become members of the new target the moment it exists. Names matter: get
them wrong and Xcode makes a second folder.

1. Open `ballyhoo.xcodeproj`.
2. **File → New → Target…**, then **iOS → Test → UI Testing Bundle**. Next.
3. Set **Product Name** to exactly `ballyhooUITests`. Set **Target to be
   Tested** to `ballyhoo`. Leave language as Swift, leave the bundle identifier
   at its default, and make sure **Project** is `ballyhoo`. Finish.
4. Check that `ScreenshotUITests.swift` and `SnapshotHelper.swift` now appear
   under the new `ballyhooUITests` group. If they do not, the product name did
   not match the folder — delete the target and redo step 3.
5. Delete the two files Xcode generated, `ballyhooUITests.swift` and
   `ballyhooUITestsLaunchTests.swift` (right-click → Delete → Move to Trash).
   The launch-performance test in the second one relaunches the app several
   times on every run and can fail on its own; neither is capturing anything.
6. **Product → Scheme → Edit Scheme…** with the `ballyhoo` scheme selected.
   Under **Test**, press **+**, add `ballyhooUITests`, and confirm the Test
   action's **Build Configuration** is **Debug** — the mock-data switch is
   behind `#if DEBUG`.
7. **Product → Scheme → Manage Schemes…** and tick **Shared** next to
   `ballyhoo`. The scheme is currently auto-generated per user, which works on
   this machine and nowhere else. This writes
   `ballyhoo.xcodeproj/xcshareddata/xcschemes/ballyhoo.xcscheme`; commit it.
8. `bundle exec fastlane screenshots`.

`SnapshotHelper.swift` is fastlane's, copied verbatim from the pinned version.
Replace it wholesale if fastlane asks for a newer one rather than patching it.

## What has actually been run

`build` has. It compiles the app clean on this machine and does not touch the
network or a keychain.

`screenshots` cannot run until step 8 above, `beta` and `release` cannot run
without a key that does not exist yet, and neither has been executed. The
credential handling, the signing flags and the upload options are written to the
documented behaviour of each action, not to something observed working.
