import AppIntents
import Foundation

@available(iOS 18.0, *)
struct GOLifecycleGatewayClient {
    private func call(path: String, body: [String: Any]) async throws -> [String: Any] {
        let configuration = try await GOAgentGatewayRuntime.shared.requireConfiguration()
        let token = try await configuration.tokenProvider()
        guard let url = URL(string: path, relativeTo: configuration.baseURL) else { throw GOAgentGatewayError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(configuration.agentID, forHTTPHeaderField: "X-GO-Agent-ID")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-GO-Request-ID")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-GO-Trace-ID")
        request.setValue("manage-travel", forHTTPHeaderField: "X-GO-Purpose")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw GOAgentGatewayError.invalidResponse }
        let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        guard (200..<300).contains(http.statusCode) else {
            throw GOAgentGatewayError.rejected(http.statusCode, object?["detail"].map(String.init(describing:)) ?? "request failed")
        }
        guard let root = object, let payload = root["data"] as? [String: Any] else { throw GOAgentGatewayError.invalidResponse }
        return payload
    }

    func release(reserveID: String, idempotencyKey: String) async throws -> [String: Any] {
        try await call(path: "/v1/agent/reserves/\(reserveID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? reserveID)/release",
                       body: ["idempotency_key": idempotencyKey])
    }

    func expire(reserveID: String, idempotencyKey: String) async throws -> [String: Any] {
        try await call(path: "/v1/agent/reserves/\(reserveID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? reserveID)/expire",
                       body: ["idempotency_key": idempotencyKey])
    }

    func quote(orderID: String, action: String, changes: [String: Any], idempotencyKey: String) async throws -> [String: Any] {
        try await call(path: "/v1/agent/orders/\(orderID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? orderID)/lifecycle/quote",
                       body: ["action": action.uppercased(), "changes": changes, "idempotency_key": idempotencyKey])
    }

    func execute(orderID: String, action: String, quoteID: String?, quoteHash: String, changes: [String: Any], paymentMethodID: String?, idempotencyKey: String) async throws -> [String: Any] {
        var body: [String: Any] = ["action": action.uppercased(), "quote_hash": quoteHash, "changes": changes, "idempotency_key": idempotencyKey]
        if let quoteID { body["quote_id"] = quoteID }
        if let paymentMethodID { body["payment_method_id"] = paymentMethodID }
        return try await call(path: "/v1/agent/orders/\(orderID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? orderID)/lifecycle/execute", body: body)
    }
}

@available(iOS 18.0, *)
struct ReleaseGOReservationIntent: AppIntent {
    static let title: LocalizedStringResource = "Release GO Reservation"
    static let description = IntentDescription("Release an unpaid GO reservation through canonical transaction truth.")
    static let openAppWhenRun = false
    @Parameter(title: "Reservation ID") var reservationID: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let x = try await GOLifecycleGatewayClient().release(reserveID: reservationID, idempotencyKey: UUID().uuidString)
        return .result(dialog: "GO release state: \(String(describing: x["state"] ?? "UNKNOWN"))")
    }
}

@available(iOS 18.0, *)
struct ExpireGOReservationIntent: AppIntent {
    static let title: LocalizedStringResource = "Check GO Reservation Expiry"
    static let description = IntentDescription("Apply GO's authoritative expiry gate. The device cannot force an early expiry.")
    static let openAppWhenRun = false
    @Parameter(title: "Reservation ID") var reservationID: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let x = try await GOLifecycleGatewayClient().expire(reserveID: reservationID, idempotencyKey: UUID().uuidString)
        return .result(dialog: "GO expiry state: \(String(describing: x["state"] ?? "UNKNOWN"))")
    }
}

@available(iOS 18.0, *)
struct QuoteGOAfterSalesIntent: AppIntent {
    static let title: LocalizedStringResource = "Review GO Booking Options"
    static let description = IntentDescription("Get the current authoritative cancel, change or refund quote.")
    static let openAppWhenRun = false
    @Parameter(title: "Order ID") var orderID: String
    @Parameter(title: "Action") var action: String
    @Parameter(title: "Changes JSON") var changesJSON: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let changes = try JSONSerialization.jsonObject(with: Data(changesJSON.utf8)) as? [String: Any] else { throw GOAgentGatewayError.invalidResponse }
        let q = try await GOLifecycleGatewayClient().quote(orderID: orderID, action: action, changes: changes, idempotencyKey: UUID().uuidString)
        return .result(dialog: "GO after-sales quote ready: \(String(describing: q["quote_id"] ?? q["quote_hash"] ?? "READY"))")
    }
}

@available(iOS 18.0, *)
struct ExecuteGOAfterSalesIntent: AppIntent {
    static let title: LocalizedStringResource = "Apply GO Booking Change"
    static let description = IntentDescription("Execute an explicitly accepted GO cancel, change or refund quote.")
    static let openAppWhenRun = true
    @Parameter(title: "Order ID") var orderID: String
    @Parameter(title: "Action") var action: String
    @Parameter(title: "Quote ID") var quoteID: String?
    @Parameter(title: "Quote Hash") var quoteHash: String
    @Parameter(title: "Changes JSON") var changesJSON: String
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let changes = try JSONSerialization.jsonObject(with: Data(changesJSON.utf8)) as? [String: Any] else { throw GOAgentGatewayError.invalidResponse }
        let configuration = try await GOAgentGatewayRuntime.shared.requireConfiguration()
        let paymentMethodID = action.uppercased() == "CHANGE" ? try await configuration.travelerPaymentMethodProvider() : nil
        let x = try await GOLifecycleGatewayClient().execute(orderID: orderID, action: action, quoteID: quoteID, quoteHash: quoteHash, changes: changes, paymentMethodID: paymentMethodID, idempotencyKey: UUID().uuidString)
        return .result(dialog: "GO \(action.lowercased()) completed: \(String(describing: x["transaction_version"] ?? "UPDATED"))")
    }
}
