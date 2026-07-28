import SwiftUI

/// Full-width row used in the main feed.
struct EventRowCard: View {
    let event: Event
    let isSaved: Bool
    let onToggleSave: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 13) {
            EventThumbnail(event: event)
                .frame(width: 78, height: 78)

            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .top, spacing: 8) {
                    Text(event.title)
                        .font(.headline)
                        .foregroundStyle(Theme.ink)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)

                    Spacer(minLength: 0)

                    SaveButton(isSaved: isSaved, action: onToggleSave)
                }

                Label(event.timeRangeLabel, systemImage: "clock")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                    .labelStyle(.compactLabel)

                Label(event.locationLabel, systemImage: "mappin.and.ellipse")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                    .labelStyle(.compactLabel)
                    .lineLimit(1)

                // This row is only 241pt wide on a 390pt phone once the feed
                // padding, card padding and thumbnail are subtracted, so a
                // badge that says nothing is expensive. Omitted rather than
                // emptied: a false `if` drops the subview and its 6pt of
                // spacing, where a zero-size placeholder would still indent
                // the category tag by 6pt.
                HStack(spacing: 6) {
                    if event.price.isKnown {
                        PriceBadge(price: event.price)
                    }
                    if let category = event.categories.first {
                        CategoryTag(category: category)
                    }
                    Spacer(minLength: 0)
                    SourceTag(source: event.source)
                }
                .padding(.top, 2)
            }
        }
        .padding(13)
        .background(Theme.surface, in: .rect(cornerRadius: Theme.Radius.card))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card)
                .stroke(Theme.hairline, lineWidth: 1)
        )
    }
}

/// Compact card for the horizontally scrolling highlight rails.
struct EventHighlightCard: View {
    let event: Event

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EventThumbnail(event: event, cornerRadius: 0)
                .frame(height: 104)
                .overlay(alignment: .topLeading) {
                    if event.isHappeningNow {
                        HappeningNowBadge()
                            .padding(8)
                    }
                }

            VStack(alignment: .leading, spacing: 4) {
                Text(event.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)

                Text("\(event.start.relativeDayLabel) · \(event.start.shortTimeLabel)")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSecondary)

                Text(event.venue?.neighborhood ?? event.venue?.name ?? "Portland")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .lineLimit(1)

                if event.price.isKnown {
                    PriceBadge(price: event.price)
                        .padding(.top, 2)
                }
            }
            .padding(11)
            .frame(maxHeight: .infinity, alignment: .top)
        }
        .frame(width: 190)
        .frame(maxHeight: .infinity)
        .background(Theme.surface, in: .rect(cornerRadius: Theme.Radius.card))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card)
                .stroke(Theme.hairline, lineWidth: 1)
        )
        .clipShape(.rect(cornerRadius: Theme.Radius.card))
    }
}

// MARK: - Save button

struct SaveButton: View {
    let isSaved: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: isSaved ? "bookmark.fill" : "bookmark")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(isSaved ? Theme.rose : Theme.inkSecondary)
                .contentTransition(.symbolEffect(.replace))
                .frame(width: 30, height: 30)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(isSaved ? "Remove from saved" : "Save event")
    }
}

// MARK: - Label style

/// Tighter icon/title spacing than the default, with a fixed icon column so
/// stacked metadata rows align.
struct CompactLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 5) {
            configuration.icon
                .font(.caption)
                .frame(width: 13)
            configuration.title
        }
    }
}

extension LabelStyle where Self == CompactLabelStyle {
    static var compactLabel: CompactLabelStyle { CompactLabelStyle() }
}
