# Verification record — 2026-10-04

| Check | Outcome |
|---|---|
| Generate Xcode project, shared scheme and Python frame fixture | Passed after fixing a generator argument-name collision |
| Python artifact/fixture suite, 5 tests | Passed |
| Source review: hello before heartbeats, bounded connection count, stale callbacks after stop, peer closure ownership | Reviewed; initialization ordering and a closure retention cycle corrected |
| Swift package tests, 29 XCTest methods | Written; not run (Swift toolchain unavailable) |
| Xcode iOS Simulator build | Not run (requires Mac/Xcode) |
| SwiftUI screen inspection | Not run |
| Swift/Python and phone-to-phone live transfer | Not run |
| macOS GitHub Actions | Prepared locally; not run/pushed |
| Native report save/reload/export, 6 additional Swift tests | Written; not run |

Report follow-up: added atomic checkpoints, saved coordinator history and system-share
JSON export. Result acceptance uses a temporary ledger copy and commits the live ledger
only after saving. Added six tests for identity/provenance round-trip, duplicate rejection,
input identity validation, checkpoint replacement, encoding failure preservation and
unfinished/corrupt reports. Five existing Windows checks passed again; they do NOT
execute this persistence code or verify the native report format. Mac testing is required.

Python checks verify saved files and fixture compatibility; they do not prove Swift
compilation, runtime behavior, UI correctness, or network compatibility on iOS.
Run `bash tools/test_on_mac.sh` on the Mac, then follow the device steps in README.md.
Failures there must be fixed before considering native milestone 1 complete.

Batch follow-up: added file-backed multiple-image selection, 500-image/16 MiB per-file
limits, atomic selection replacement, three scheduling policies, worker-count startup
gate and ten further tests. Re-ran the three Windows checks successfully. New Swift
tests cover ownership, lost owners, late joiners, single-worker exclusion, next-available
allocation, incorrect image IDs, copy independence, rollback, and file size errors.
These tests have not executed; no native scheduling or file-import pass is claimed.

Discovery follow-up: implemented Bonjour listener advertisement, named coordinator
selection, browser refresh/cancellation, unavailable-network guidance and manual IP
fallback. Added six Swift state tests covering duplicate entries, removed services,
late callbacks, failure/retry, equal names in different domains and service filtering.
Regenerated the Xcode project to include SessionDiscovery.swift. Five Windows checks
passed, including matching Info.plist service declaration and actual build-phase source
coverage. Bonjour network behavior, permission prompts and Swift compilation remain untested.
