// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "RescueSwarmCore",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "RescueSwarmCore", targets: ["RescueSwarmCore"])],
    targets: [
        .target(name: "RescueSwarmCore"),
        .testTarget(name: "RescueSwarmCoreTests", dependencies: ["RescueSwarmCore"],
                    resources: [.copy("Fixtures")])
    ]
)
