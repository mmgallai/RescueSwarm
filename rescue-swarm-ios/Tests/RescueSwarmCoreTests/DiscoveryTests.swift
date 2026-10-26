import XCTest
@testable import RescueSwarmCore

final class DiscoveryTests: XCTestCase {
    private func session(_ name: String, domain: String = "local.") -> DiscoveredSession {
        DiscoveredSession(name: name, type: DiscoveryState.serviceType, domain: domain)
    }
    func testSnapshotDeduplicatesAndSorts() {
        var state = DiscoveryState()
        let token = state.begin()
        state.update([session("b"), session("a"), session("b")], generation: token)
        XCTAssertEqual(state.sessions.map(\.name), ["a", "b"])
    }
    func testRemovedSessionDisappears() {
        var state = DiscoveryState()
        let token = state.begin()
        state.update([session("a"), session("b")], generation: token)
        state.update([session("b")], generation: token)
        XCTAssertEqual(state.sessions, [session("b")])
        state.update([], generation: token)
        XCTAssertTrue(state.sessions.isEmpty)
    }
    func testOldBrowserCannotRepopulateAfterRefreshOrStop() {
        var state = DiscoveryState()
        let old = state.begin()
        let current = state.begin()
        state.update([session("old")], generation: old)
        state.fail("late error", generation: old)
        XCTAssertTrue(state.sessions.isEmpty)
        XCTAssertNil(state.problem)
        state.update([session("current")], generation: current)
        state.stop()
        state.update([session("current")], generation: current)
        XCTAssertTrue(state.sessions.isEmpty)
        XCTAssertFalse(state.searching)
    }
    func testErrorClearsEndpointsAndRetryResetsError() {
        var state = DiscoveryState()
        let token = state.begin()
        state.update([session("a")], generation: token)
        state.fail("Permission unavailable", generation: token)
        state.update([session("late")], generation: token)
        XCTAssertTrue(state.sessions.isEmpty)
        XCTAssertFalse(state.searching)
        XCTAssertNotNil(state.problem)
        _ = state.begin()
        XCTAssertNil(state.problem)
        XCTAssertTrue(state.searching)
    }
    func testSameNameDifferentDomainsRemainDistinct() {
        var state = DiscoveryState()
        let token = state.begin()
        state.update([session("Team", domain: "local."), session("Team", domain: "example.")], generation: token)
        XCTAssertEqual(state.sessions.count, 2)
        XCTAssertNotEqual(state.sessions[0].id, state.sessions[1].id)
    }
    func testFiltersUnrelatedServicesAndNormalizesTrailingDot() {
        var state = DiscoveryState()
        let token = state.begin()
        state.update([DiscoveredSession(name: "wrong", type: "_other._tcp", domain: "local."),
                      session(""), DiscoveredSession(name: "valid", type: "_rescueswarm._tcp.", domain: "local.")], generation: token)
        XCTAssertEqual(state.sessions, [session("valid")])
    }
}
