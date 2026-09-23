// swift-tools-version:5.9
// AtlasKit: native macOS pieces of Atlas (IPC client, Keychain store). Built and tested on the macOS CI
// runner. Interactive app, Supervisor and VM are separate targets that still require a real Mac (D-01).
import PackageDescription

let package = Package(
    name: "AtlasKit",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "AtlasKit", targets: ["AtlasKit"]),
        .executable(name: "atlas-ipc-probe", targets: ["atlas-ipc-probe"]),
    ],
    targets: [
        .target(name: "AtlasKit"),
        .executableTarget(name: "atlas-ipc-probe", dependencies: ["AtlasKit"]),
        .testTarget(name: "AtlasKitTests", dependencies: ["AtlasKit"]),
    ]
)
