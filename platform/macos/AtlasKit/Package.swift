// swift-tools-version:5.9
// AtlasKit: native macOS pieces of Atlas (IPC client, Keychain store). Built and tested on the macOS CI
// runner. Interactive app, Supervisor and VM are separate targets that still require a real Mac (D-01).
import PackageDescription

let package = Package(
    name: "AtlasKit",
    // Compile floor only. Homologated on macOS 15 (CI runner) - the bundle declares 15.0 as minimum.
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "AtlasKit", targets: ["AtlasKit"]),
        .executable(name: "atlas-ipc-probe", targets: ["atlas-ipc-probe"]),
        .executable(name: "atlas-keychain-agent", targets: ["atlas-keychain-agent"]),
        .executable(name: "atlas-bundle-check", targets: ["atlas-bundle-check"]),
        .executable(name: "AtlasApp", targets: ["AtlasApp"]),
    ],
    targets: [
        .target(name: "AtlasKit"),
        .executableTarget(name: "atlas-ipc-probe", dependencies: ["AtlasKit"]),
        .executableTarget(name: "atlas-keychain-agent", dependencies: ["AtlasKit"]),
        .executableTarget(name: "atlas-bundle-check", dependencies: ["AtlasKit"]),
        .executableTarget(name: "AtlasApp", dependencies: ["AtlasKit"]),
        .testTarget(name: "AtlasKitTests", dependencies: ["AtlasKit"]),
    ]
)
