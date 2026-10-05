"""Windows-runnable artifact/fixture checks. These DO NOT compile or execute Swift."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_xcode_sources_and_package_references(self):
        project = plistlib.loads((ROOT/"RescueSwarm.xcodeproj/project.pbxproj").read_bytes())
        objects = project["objects"]
        self.assertEqual(objects[project["rootObject"]]["isa"], "PBXProject")
        references = [v for v in objects.values() if v["isa"] == "PBXFileReference" and v.get("sourceTree") == "<group>"]
        for ref in references:
            self.assertTrue((ROOT/ref["path"]).is_file(), ref)
        sources = {v["path"] for v in references if v["path"].endswith(".swift")}
        self.assertEqual(sources, {str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT/"App").glob("*.swift")})
        self.assertTrue((ROOT/"Package.swift").is_file())
        scheme = ET.parse(ROOT/"RescueSwarm.xcodeproj/xcshareddata/xcschemes/RescueSwarm.xcscheme")
        for ref in scheme.findall(".//BuildableReference"):
            self.assertEqual(objects[ref.attrib["BlueprintIdentifier"]]["isa"], "PBXNativeTarget")

    def test_local_network_usage_declared(self):
        info = plistlib.loads((ROOT/"App/Info.plist").read_bytes())
        self.assertTrue(info["NSLocalNetworkUsageDescription"])

    def test_bonjour_declaration_matches_shared_service_type(self):
        info = plistlib.loads((ROOT/"App/Info.plist").read_bytes())
        source = (ROOT/"Sources/RescueSwarmCore/DiscoveryState.swift").read_text()
        service_type = re.search(r'serviceType = "([^"]+)"', source).group(1)
        self.assertIn(service_type, info["NSBonjourServices"])
        self.assertLessEqual(len(service_type.split(".")[0].lstrip("_")), 15)

    def test_build_phase_contains_all_app_sources(self):
        project = plistlib.loads((ROOT/"RescueSwarm.xcodeproj/project.pbxproj").read_bytes())
        objects = project["objects"]
        compiled = set()
        for phase in objects.values():
            if phase["isa"] == "PBXSourcesBuildPhase":
                for build_id in phase["files"]:
                    compiled.add(objects[objects[build_id]["fileRef"]]["path"])
        self.assertEqual(compiled, {"App/"+p.name for p in (ROOT/"App").glob("*.swift")})

    def test_golden_fixture_framing_and_checksum(self):
        data = (ROOT/"Tests/RescueSwarmCoreTests/Fixtures/python-task.bin").read_bytes()
        length, = struct.unpack("!I", data[:4])
        self.assertTrue(0 < length <= 64 * 1024)
        header = json.loads(data[4:4+length])
        payload = data[4+length:]
        self.assertEqual(header["payload_bytes"], len(payload))
        self.assertEqual(header["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(header["image_id"], "fixture.ppm")
        self.assertEqual(len(payload), 23)


if __name__ == "__main__":
    unittest.main()
