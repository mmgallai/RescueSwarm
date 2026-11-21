import Foundation
import XCTest
@testable import RescueSwarmGeolocation

final class GeolocationTests: XCTestCase {
    func message(_ box: [Double] = [300,200,340,240]) -> DetectionResult {
        DetectionResult(status: "success", imageSize: DetectionImageSize(width:640,height:480),
            detections:[PersonDetection(confidence:0.9,boxXYXY:box)])
    }
    func attribute(_ xml: String, _ name: String) -> String {
        let prefix = name + "=\""
        return String(xml.components(separatedBy: prefix)[1].prefix(while: { $0 != "\"" }))
    }
    func event(uid: String? = nil) throws -> String {
        try geolocatePerson(message(),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:90,verticalFOVDegrees:60,uid:uid)
    }
    func testDistinctSightingsAndStableExplicitUID() throws {
        XCTAssertNotEqual(attribute(try event(),"uid"), attribute(try event(),"uid"))
        XCTAssertEqual(attribute(try event(uid:"run/image/person0"),"uid"),"run/image/person0")
        XCTAssertTrue(try event(uid:"person<&\"").contains("person&lt;&amp;&quot;"))
    }
    func testUnknownHeightIsNotZero() throws {
        let xml = try event()
        XCTAssertEqual(Double(attribute(xml,"hae")),cotUnknown)
        XCTAssertEqual(Double(attribute(xml,"ce")),cotUnknown)
        XCTAssertTrue(xml.contains("flat-ground assumption"))
    }
    func testHeightDatumsAndConversion() throws {
        for (datum,offset,expected) in [(TerrainDatum.msl,nil,cotUnknown),(.msl,30.0,230.0),(.msl,-30.0,170.0),(.hae,nil,200.0)] {
            let xml = try geolocatePerson(message(),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
                horizontalFOVDegrees:90,verticalFOVDegrees:60,elevationProvider:{_,_ in 200},
                terrainDatum:datum,geoidOffsetMeters:offset)
            XCTAssertEqual(Double(attribute(xml,"hae"))!,expected,accuracy:0.1)
        }
    }
    func testOldNoHitCaseReachesGround() throws {
        let xml = try geolocatePerson(message([620,200,640,240]),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:170,verticalFOVDegrees:60,elevationProvider:{_,_ in 0},terrainDatum:.hae)
        XCTAssertEqual(Double(attribute(xml,"hae"))!,0,accuracy:0.1)
        let east = 100 * (630.0/640 - 0.5) * 2 * tan(85 * Double.pi/180)
        XCTAssertEqual(Double(attribute(xml,"lon"))!,east/6371000*180/Double.pi,accuracy:1e-6)
    }
    func testNoIntersectionThrows() {
        XCTAssertThrowsError(try geolocatePerson(message([620,200,640,240]),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:179.9,verticalFOVDegrees:60,elevationProvider:{_,_ in 0}))
    }
    func testAnalyticSlope() throws {
        let xml = try geolocatePerson(message([460,200,500,240]),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:90,verticalFOVDegrees:60,elevationProvider:{_,lon in 0.2*lon*Double.pi/180*6371000},terrainDatum:.hae)
        XCTAssertEqual(Double(attribute(xml,"hae"))!,100-100/1.1,accuracy:0.1)
        XCTAssertEqual(Double(attribute(xml,"lon"))!,50/1.1/6371000*180/Double.pi,accuracy:1e-6)
    }
    func testMissingTerrainMidRayThrows() {
        XCTAssertThrowsError(try geolocatePerson(message([460,200,500,240]),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:90,verticalFOVDegrees:60,elevationProvider:{_,lon in lon==0 ? 0 : nil}))
    }
    func testNonFiniteTerrainThrows() {
        XCTAssertThrowsError(try geolocatePerson(message(),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:90,verticalFOVDegrees:60,elevationProvider:{_,_ in .nan}))
    }
    func testCameraLookupFallbackIsExplicit() throws {
        var warnings:[String]=[]
        let xml = try geolocatePerson(message(),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:90,verticalFOVDegrees:60,elevationProvider:{_,_ in nil},warningHandler:{ warnings.append($0) })
        XCTAssertEqual(warnings.count,1)
        XCTAssertTrue(xml.contains("flat-ground assumption"))
    }
    func testTiltIsRejected() {
        XCTAssertThrowsError(try geolocatePerson(message(),cameraLatitude:0,cameraLongitude:0,altitudeMeters:100,
            horizontalFOVDegrees:90,verticalFOVDegrees:60,cameraPitchDegrees:-45))
    }
    func testWireResultAdapter() throws {
        let json = #"{"status":"success","image_size":{"width":640,"height":480},"detections":[{"label":"person","confidence":0.9,"box_xyxy":[300,200,340,240]}],"task_id":1,"attempt_id":2,"detector_config":{"imgsz":1280}}"#
        let result = try JSONDecoder().decode(DetectionResult.self,from:Data(json.utf8))
        let xml = try geolocatePerson(result,cameraLatitude:37,cameraLongitude:-122,altitudeMeters:100,
            horizontalFOVDegrees:90,verticalFOVDegrees:60,flatGroundHAEMeters:200)
        XCTAssertEqual(Double(attribute(xml,"lat")),37)
        XCTAssertEqual(Double(attribute(xml,"lon")),-122)
        XCTAssertEqual(Double(attribute(xml,"hae")),200)
    }
}
