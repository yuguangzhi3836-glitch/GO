import AppIntents
import Foundation

@available(iOS 18.0, *)
struct GOAgentRuntimeConfiguration: Sendable {
    let baseURL: URL
    let agentID: String
    let tokenProvider: @Sendable () async throws -> String
    let travelerPaymentMethodProvider: @Sendable () async throws -> String
}

@available(iOS 18.0, *)
actor GOAgentGatewayRuntime {
    static let shared = GOAgentGatewayRuntime()
    private var configuration: GOAgentRuntimeConfiguration?
    func configure(_ value: GOAgentRuntimeConfiguration) { configuration = value }
    func requireConfiguration() throws -> GOAgentRuntimeConfiguration {
        guard let configuration else { throw GOAgentGatewayError.notConfigured }
        return configuration
    }
}

@available(iOS 18.0, *)
enum GOAgentGatewayError: LocalizedError {
    case notConfigured
    case invalidResponse
    case rejected(Int, String)
    var errorDescription: String? {
        switch self {
        case .notConfigured: return "GO secure agent runtime is not configured."
        case .invalidResponse: return "GO returned an invalid transaction response."
        case let .rejected(code, message): return "GO rejected the transaction (\(code)): \(message)"
        }
    }
}

@available(iOS 18.0, *)
actor GOOfferCache {
    static let shared = GOOfferCache()
    private var offers: [String: GOOfferEntity] = [:]
    func put(_ offer: GOOfferEntity) { offers[offer.id] = offer }
    func get(_ id: String) -> GOOfferEntity? { offers[id] }
    func all() -> [GOOfferEntity] { Array(offers.values) }
}

@available(iOS 18.0, *)
struct GOAgentGatewayClient {
    private func call(path: String, method: String = "POST", body: [String: Any]? = nil, purpose: String = "book-travel") async throws -> [String: Any] {
        let configuration = try await GOAgentGatewayRuntime.shared.requireConfiguration()
        let token = try await configuration.tokenProvider()
        guard let url = URL(string: path, relativeTo: configuration.baseURL) else { throw GOAgentGatewayError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(configuration.agentID, forHTTPHeaderField: "X-GO-Agent-ID")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-GO-Request-ID")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-GO-Trace-ID")
        request.setValue(purpose, forHTTPHeaderField: "X-GO-Purpose")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw GOAgentGatewayError.invalidResponse }
        let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        guard (200..<300).contains(http.statusCode) else {
            throw GOAgentGatewayError.rejected(http.statusCode, object?["detail"].map(String.init(describing:)) ?? "request failed")
        }
        guard let root = object, let payload = root["data"] as? [String: Any] else { throw GOAgentGatewayError.invalidResponse }
        return payload
    }

    func search(productType: String, search: [String: Any]) async throws -> [[String: Any]] {
        let data = try await call(path: "/v1/agent/offers", body: ["product_type": productType, "search": search])
        return data["items"] as? [[String: Any]] ?? []
    }

    func reserve(offer: GOOfferEntity, booking: [String: Any], idempotencyKey: String) async throws -> [String: Any] {
        try await call(path: "/v1/agent/reserves", body: ["offer_id": offer.id, "quote_hash": offer.quoteHash, "search": offer.search, "booking": booking, "idempotency_key": idempotencyKey])
    }

    func preparePayment(reserveID: String, totalMinor: Int, currency: String, idempotencyKey: String) async throws -> [String: Any] {
        let configuration = try await GOAgentGatewayRuntime.shared.requireConfiguration()
        let paymentMethodID = try await configuration.travelerPaymentMethodProvider()
        return try await call(path: "/v1/agent/payments", body: ["reserve_id": reserveID, "expected_total_minor": totalMinor, "currency": currency, "payment_method_id": paymentMethodID, "idempotency_key": idempotencyKey], purpose: "pay-travel")
    }

    func commit(reserveID: String, paymentTruthID: String, idempotencyKey: String) async throws -> [String: Any] {
        try await call(path: "/v1/agent/commits", body: ["reserve_id": reserveID, "payment_truth_id": paymentTruthID, "idempotency_key": idempotencyKey])
    }

    func order(orderID: String) async throws -> [String: Any] {
        try await call(path: "/v1/agent/orders/\(orderID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? orderID)", method: "GET")
    }
}

@available(iOS 18.0, *)
struct GOOfferEntity: AppEntity, Identifiable {
    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "GO Offer")
    static let defaultQuery = GOOfferQuery()
    let id: String
    let title: String
    let productType: String
    let totalMinor: Int
    let currency: String
    let quoteHash: String
    let search: [String: String]
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(title)", subtitle: "\(currency) \(Double(totalMinor) / 100.0)") }
}

@available(iOS 18.0, *)
struct GOOfferQuery: EntityQuery {
    func entities(for identifiers: [GOOfferEntity.ID]) async throws -> [GOOfferEntity] {
        var result: [GOOfferEntity] = []
        for id in identifiers { if let offer = await GOOfferCache.shared.get(id) { result.append(offer) } }
        return result
    }
    func suggestedEntities() async throws -> [GOOfferEntity] { await GOOfferCache.shared.all() }
}

@available(iOS 18.0, *)
struct SearchGOTravelOffersIntent: AppIntent {
    static let title: LocalizedStringResource = "Search GO Travel Offers"
    static let description = IntentDescription("Search verified machine-executable travel offers through GO.")
    static let openAppWhenRun = false
    @Parameter(title: "Product type") var productType: String
    @Parameter(title: "Search JSON") var searchJSON: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let search = try JSONSerialization.jsonObject(with: Data(searchJSON.utf8)) as? [String: Any] else { throw GOAgentGatewayError.invalidResponse }
        let offers = try await GOAgentGatewayClient().search(productType: productType.uppercased(), search: search)
        for item in offers {
            guard let id=item["offer_id"] as? String, let type=item["product_type"] as? String, let total=item["total_minor"] as? Int, let currency=item["currency"] as? String, let quote=item["quote_hash"] as? String else { continue }
            let searchStrings=search.reduce(into:[String:String]()){ $0[$1.key]=String(describing:$1.value) }
            await GOOfferCache.shared.put(GOOfferEntity(id:id,title:item["product_id"] as? String ?? id,productType:type,totalMinor:total,currency:currency,quoteHash:quote,search:searchStrings))
        }
        return .result(dialog: "GO found \(offers.count) verified offer(s).")
    }
}

@available(iOS 18.0, *)
struct ReserveGOOfferIntent: AppIntent {
    static let title: LocalizedStringResource = "Reserve GO Offer"
    static let description = IntentDescription("Reserve a selected GO quote through the canonical transaction core.")
    static let openAppWhenRun = false
    @Parameter(title: "Offer") var offer: GOOfferEntity
    @Parameter(title: "Booking JSON") var bookingJSON: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let booking = try JSONSerialization.jsonObject(with: Data(bookingJSON.utf8)) as? [String: Any] else { throw GOAgentGatewayError.invalidResponse }
        let result=try await GOAgentGatewayClient().reserve(offer:offer,booking:booking,idempotencyKey:UUID().uuidString)
        return .result(dialog: "GO reservation created: \(result["reserve_id"].map(String.init(describing:)) ?? "")")
    }
}

@available(iOS 18.0, *)
struct PrepareGOPaymentTruthIntent: AppIntent {
    static let title: LocalizedStringResource = "Authorize GO Payment"
    static let description = IntentDescription("Establish GO payment truth using the app's secure payment method.")
    static let openAppWhenRun = true
    @Parameter(title: "Reservation ID") var reservationID: String
    @Parameter(title: "Total minor units") var totalMinor: Int
    @Parameter(title: "Currency") var currency: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let result=try await GOAgentGatewayClient().preparePayment(reserveID:reservationID,totalMinor:totalMinor,currency:currency.uppercased(),idempotencyKey:UUID().uuidString)
        return .result(dialog: "GO payment authorization is ready: \(result["payment_truth_id"].map(String.init(describing:)) ?? "")")
    }
}

@available(iOS 18.0, *)
struct CommitGOReservationIntent: AppIntent {
    static let title: LocalizedStringResource = "Confirm GO Booking"
    static let description = IntentDescription("Commit a GO reservation only against matching GO payment truth.")
    static let openAppWhenRun = true
    @Parameter(title: "Reservation ID") var reservationID: String
    @Parameter(title: "Payment truth ID") var paymentTruthID: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let order=try await GOAgentGatewayClient().commit(reserveID:reservationID,paymentTruthID:paymentTruthID,idempotencyKey:UUID().uuidString)
        return .result(dialog: "GO booking confirmed: \(order["order_id"].map(String.init(describing:)) ?? "")")
    }
}

@available(iOS 18.0, *)
struct GOTravelShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: SearchGOTravelOffersIntent(), phrases: ["Search travel with \(.applicationName)"])
        AppShortcut(intent: ReserveGOOfferIntent(), phrases: ["Reserve my GO offer with \(.applicationName)"])
        AppShortcut(intent: PrepareGOPaymentTruthIntent(), phrases: ["Authorize my GO travel payment with \(.applicationName)"])
        AppShortcut(intent: CommitGOReservationIntent(), phrases: ["Confirm my GO booking with \(.applicationName)"])
    }
}
