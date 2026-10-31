// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "NFSMWBuilder",
    platforms: [.macOS(.v12)],
    targets: [
        .target(name: "BuilderCore"),
        .executableTarget(name: "NFSMWBuilder", dependencies: ["BuilderCore"]),
        .testTarget(name: "BuilderCoreTests", dependencies: ["BuilderCore"]),
    ]
)
