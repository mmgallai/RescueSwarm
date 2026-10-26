// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "RescueSwarmGeolocation",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "RescueSwarmGeolocation", targets: ["RescueSwarmGeolocation"])],
    targets: [
        .target(name: "RescueSwarmGeolocation", path: ".", exclude: ["Tests", "Package.swift"], sources: ["Geolocate.swift"]),
        .testTarget(name: "GeolocationTests", dependencies: ["RescueSwarmGeolocation"], path: "Tests")
    ]
)
