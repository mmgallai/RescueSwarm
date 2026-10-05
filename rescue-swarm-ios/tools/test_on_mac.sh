#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p TestResults
swift test 2>&1 | tee TestResults/swift-tests.log
xcodebuild -project RescueSwarm.xcodeproj -scheme RescueSwarm \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath DerivedData CODE_SIGNING_ALLOWED=NO build \
  2>&1 | tee TestResults/ios-build.log
