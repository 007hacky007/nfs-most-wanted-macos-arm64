// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "NFSMWBuilder",
    platforms: [.macOS(.v12)],
    targets: [
        .target(name: "BuilderCore"),
        .executableTarget(name: "NFSMWBuilder", dependencies: ["BuilderCore"]),
        // Fixtures are read through #filePath; tests/test_builder_events_fixture.py keeps them current.
        .testTarget(name: "BuilderCoreTests", dependencies: ["BuilderCore"], exclude: ["Fixtures"]),
    ]
)
