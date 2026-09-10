import AppIntents
import Foundation

@available(iOS 18.0, *)
struct GOOfferEntity: AppEntity, Identifiable {
    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "GO Offer")
    static var defaultQuery = GOOfferQuery()

    let id: String
    let title: String
    let totalMinor: Int
    let currency: String
    let expiresAt: Date

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(title)", subtitle: "\(currency) \(Double(totalMinor) / 100.0)")
    }
}

@available(iOS 18.0, *)
struct GOOfferQuery: EntityQuery {
    func entities(for identifiers: [GOOfferEntity.ID]) async throws -> [GOOfferEntity] {
        // Native target must bind this to the authenticated GO Agent Gateway client.
        // Never resolve offer truth from local cache for a financial mutation.
        []
    }

    func suggestedEntities() async throws -> [GOOfferEntity] { [] }
}

@available(iOS 18.0, *)
struct SearchGOTravelOffersIntent: AppIntent {
    static var title: LocalizedStringResource = "Search GO Travel Offers"
    static var description = IntentDescription("Search machine-executable travel offers through GO.")
    static var openAppWhenRun = false

    @Parameter(title: "Trip request") var query: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        // The native bridge will exchange an Apple-authorized, purpose-bound token
        // for GO agent authorization and invoke offer.search. No booking mutation here.
        .result(dialog: "GO will search verified travel offers for this request.")
    }
}

@available(iOS 18.0, *)
struct ReserveGOOfferIntent: AppIntent {
    static var title: LocalizedStringResource = "Reserve GO Offer"
    static var description = IntentDescription("Atomically reserve a selected GO travel offer.")
    static var openAppWhenRun = false

    @Parameter(title: "Offer") var offer: GOOfferEntity

    func perform() async throws -> some IntentResult & ProvidesDialog {
        // Native bridge must generate an idempotency key and call GO reserve.
        // It must never treat Siri/App Intent invocation itself as an inventory promise.
        .result(dialog: "GO will reserve the selected offer subject to live inventory confirmation.")
    }
}

@available(iOS 18.0, *)
struct CommitGOReservationIntent: AppIntent {
    static var title: LocalizedStringResource = "Confirm GO Booking"
    static var description = IntentDescription("Commit a valid GO reservation after payment success.")
    static var openAppWhenRun = true

    @Parameter(title: "Reservation ID") var reservationID: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        // Payment success must be established by GO's licensed payment truth path.
        // This intent may request commit only after the gateway has a valid payment_intent_id.
        .result(dialog: "Open GO to authorize and confirm this booking securely.")
    }
}

@available(iOS 18.0, *)
struct GOTravelShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: SearchGOTravelOffersIntent(), phrases: ["Search travel with \(.applicationName)"])
        AppShortcut(intent: ReserveGOOfferIntent(), phrases: ["Reserve my GO offer with \(.applicationName)"])
    }
}
