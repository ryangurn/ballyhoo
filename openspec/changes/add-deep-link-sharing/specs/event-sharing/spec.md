## ADDED Requirements

### Requirement: The share payload is self-contained

Sharing an event SHALL produce a payload that conveys the event without depending on any link resolving. The payload SHALL contain the event's title, its start date and time, its venue name when one is known, an attribution line naming the source, the upstream listing URL when one exists, and the canonical HTTPS deep link.

#### Scenario: A shared event read after the link has decayed

- **WHEN** a recipient reads a shared payload months later, after the event has dropped out of the feed
- **THEN** the message still tells them the event's name, when it was, where it was, and which source listed it, without any link needing to resolve

#### Scenario: An event with no venue

- **WHEN** an event has no venue
- **THEN** the payload omits the venue rather than emitting an empty separator or a placeholder

#### Scenario: The deep link is placed last

- **WHEN** a payload is composed
- **THEN** the canonical deep link is the final line, so messaging clients have the best chance of rendering a link preview for it

### Requirement: Attribution is present in every share payload

Every share payload SHALL name the event's source. Attribution SHALL be part of the payload's own text rather than carried in a share-sheet field whose delivery depends on the destination app, because Calagator's CC BY licence and Ticketmaster's terms make attribution a condition of redistribution rather than a presentation preference.

#### Scenario: Attribution survives every destination

- **WHEN** a payload is shared to Messages, Mail, Slack, or the clipboard
- **THEN** the source name is present in the delivered text in every case

#### Scenario: Attribution is present without an upstream URL

- **WHEN** an event has no `listing_url`
- **THEN** the payload still names the source, omitting only the URL

### Requirement: The share payload excludes upstream description text

The payload SHALL NOT include the event's `summary`. It SHALL be limited to factual scheduling details, attribution, and links.

#### Scenario: An event with a long description

- **WHEN** an event carries a multi-paragraph summary
- **THEN** the payload contains the title, time, venue, attribution, and links only, and remains short enough to read at a glance in a message

#### Scenario: Redistribution stays within licence terms

- **WHEN** an event sourced from Ticketmaster is shared into a public channel
- **THEN** no upstream marketing copy is republished, only the factual details of a public event plus attribution

### Requirement: Sharing the upstream listing remains a separate action

The app SHALL offer a secondary share action that shares the upstream `listing_url` on its own as a URL, distinct from the primary payload share. The action SHALL be labelled with the destination source's name so the user knows where the link points before sending it.

#### Scenario: Sharing a ticketed event's listing directly

- **WHEN** a user wants to send a friend the Ticketmaster page for a concert, with that site's own link preview
- **THEN** a secondary action labelled with the source shares the bare upstream URL, rather than the Ballyhoo payload

#### Scenario: The secondary action is absent when there is nothing to link

- **WHEN** an event has no `listing_url`
- **THEN** the secondary action is not offered, and only the primary payload share is available

#### Scenario: The ticket URL is not a third action

- **WHEN** an event carries a `ticket_url` distinct from its `listing_url`
- **THEN** no additional share action is offered for it

### Requirement: Every event is shareable

A share affordance SHALL be available for every event regardless of whether it has an upstream `listing_url`, replacing the previous behaviour where the absence of a listing URL removed the share control entirely.

#### Scenario: Sharing an event with no upstream URL

- **WHEN** the user opens an event that has no `listing_url`
- **THEN** the primary share action is present and produces a payload containing the title, time, venue, attribution, and the deep link

#### Scenario: The primary action stays a single tap

- **WHEN** the user taps the share control in the event detail toolbar
- **THEN** the share sheet for the primary payload opens directly, with the secondary listing action reachable but not in the way
