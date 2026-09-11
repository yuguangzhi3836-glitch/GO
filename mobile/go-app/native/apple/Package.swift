// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "GOAgentTransactionProtocol",
    platforms: [.iOS(.v18)],
    products: [
        .library(name: "GOAgentTransactionProtocol", targets: ["GOAgentTransactionProtocol"])
    ],
    targets: [
        .target(
            name: "GOAgentTransactionProtocol",
            path: ".",
            exclude: ["Package.swift"],
            sources: ["GOTravelTransactionIntents.swift", "GOTransactionLifecycleIntents.swift"],
            swiftSettings: [.swiftLanguageMode(.v6)]
        )
    ]
)
