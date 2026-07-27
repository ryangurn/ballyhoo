import SwiftUI

// MARK: - Thumbnail

/// Event artwork, falling back to a deterministic gradient when a listing has
/// no image — which is most community listings.
struct EventThumbnail: View {
    let event: Event
    var cornerRadius: CGFloat = Theme.Radius.thumbnail

    var body: some View {
        ZStack {
            event.placeholderGradient

            if let imageURL = event.imageURL {
                AsyncImage(url: imageURL) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFill()
                    }
                }
            } else {
                Image(systemName: event.primaryCategory.symbol)
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(.white.opacity(0.85))
            }
        }
        .clipShape(.rect(cornerRadius: cornerRadius))
    }
}

// MARK: - Badges

struct PriceBadge: View {
    let price: Price

    var body: some View {
        Text(price.displayText)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(price.isFree ? Theme.evergreen : Theme.ink)
            .background(
                price.isFree
                    ? Theme.evergreen.opacity(0.14)
                    : Theme.surfaceRaised,
                in: .rect(cornerRadius: 8)
            )
    }
}

struct CategoryTag: View {
    let category: Category

    var body: some View {
        Label(category.title, systemImage: category.symbol)
            .font(.caption2.weight(.medium))
            .labelStyle(.titleAndIcon)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(category.tint)
            .background(category.tint.opacity(0.13), in: .rect(cornerRadius: 7))
    }
}

/// Attribution back to the upstream source. Ticketmaster's terms and
/// Calagator's license both require this to be visible.
struct SourceTag: View {
    let source: Source

    var body: some View {
        Text(source.name)
            .font(.caption2)
            .foregroundStyle(Theme.inkSecondary)
    }
}

struct HappeningNowBadge: View {
    var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(Theme.rose)
                .frame(width: 6, height: 6)
            Text("Happening now")
                .font(.caption2.weight(.semibold))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .foregroundStyle(Theme.rose)
        .background(Theme.rose.opacity(0.12), in: .capsule)
    }
}

// MARK: - Chips

struct FilterChip: View {
    let title: String
    var systemImage: String?
    let isSelected: Bool
    var tint: Color = Theme.evergreen
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .font(.caption.weight(.semibold))
                }
                Text(title)
                    .font(.subheadline.weight(.medium))
            }
            .padding(.horizontal, 13)
            .padding(.vertical, 8)
            .foregroundStyle(isSelected ? .white : Theme.ink)
            .background(
                isSelected ? tint : Theme.surface,
                in: .rect(cornerRadius: Theme.Radius.chip)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.chip)
                    .stroke(isSelected ? .clear : Theme.hairline, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Section header

struct SectionHeader: View {
    let title: String
    var subtitle: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.title3.weight(.semibold))
                .foregroundStyle(Theme.ink)
            if let subtitle {
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Formatting

extension Date {
    /// "Today", "Tomorrow", or "Saturday, Aug 2".
    var relativeDayLabel: String {
        let calendar = Calendar.current
        if calendar.isDateInToday(self) { return "Today" }
        if calendar.isDateInTomorrow(self) { return "Tomorrow" }
        return formatted(.dateTime.weekday(.wide).month(.abbreviated).day())
    }

    var shortTimeLabel: String {
        formatted(.dateTime.hour().minute())
    }
}

extension Event {
    /// "7:00 PM", or "7:00 – 10:00 PM" when an end time is known.
    var timeRangeLabel: String {
        if isAllDay { return "All day" }
        guard let end, !Calendar.current.isDate(start, equalTo: end, toGranularity: .minute) else {
            return start.shortTimeLabel
        }
        return "\(start.shortTimeLabel) – \(end.shortTimeLabel)"
    }

    var locationLabel: String {
        guard let venue else { return "Location TBA" }
        if let neighborhood = venue.neighborhood {
            return "\(venue.name) · \(neighborhood)"
        }
        return venue.name
    }
}
