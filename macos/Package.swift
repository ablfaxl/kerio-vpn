// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "KerioVPNMac",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "KerioVPNMac", targets: ["KerioVPNMac"])],
    targets: [.executableTarget(name: "KerioVPNMac")]
)
