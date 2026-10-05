"""Generate the small Xcode project and Python-to-Swift wire fixture. No dependencies."""
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    objects = {}
    def add(identity, isa, **fields):
        key = hashlib.sha256(identity.encode()).hexdigest()[:24].upper()
        objects[key] = {"isa": isa, **fields}
        return key
    file_refs, builds = [], []
    for path in sorted((ROOT / "App").glob("*.swift")):
        ref = add(path.name, "PBXFileReference", lastKnownFileType="sourcecode.swift",
                  path="App/" + path.name, sourceTree="<group>")
        file_refs.append(ref)
        builds.append(add("build-" + path.name, "PBXBuildFile", fileRef=ref))
    plist = add("plist", "PBXFileReference", lastKnownFileType="text.plist.xml", path="App/Info.plist", sourceTree="<group>")
    product = add("product", "PBXFileReference", explicitFileType="wrapper.application", path="RescueSwarm.app", sourceTree="BUILT_PRODUCTS_DIR")
    group = add("group", "PBXGroup", children=file_refs+[plist, product], sourceTree="<group>")
    package = add("package", "XCLocalSwiftPackageReference", relativePath=".")
    library = add("library", "XCSwiftPackageProductDependency", package=package, productName="RescueSwarmCore")
    link = add("link", "PBXBuildFile", productRef=library)
    sources = add("sources", "PBXSourcesBuildPhase", buildActionMask=2147483647, files=builds, runOnlyForDeploymentPostprocessing=0)
    frameworks = add("frameworks", "PBXFrameworksBuildPhase", buildActionMask=2147483647, files=[link], runOnlyForDeploymentPostprocessing=0)
    resources = add("resources", "PBXResourcesBuildPhase", buildActionMask=2147483647, files=[], runOnlyForDeploymentPostprocessing=0)
    def configs(prefix, settings):
        refs = []
        for name in ("Debug", "Release"):
            values = {**settings, "SWIFT_OPTIMIZATION_LEVEL": "-Onone" if name == "Debug" else "-O"}
            refs.append(add(prefix+name, "XCBuildConfiguration", name=name, buildSettings=values))
        return add(prefix+"configs", "XCConfigurationList", buildConfigurations=refs, defaultConfigurationIsVisible=0, defaultConfigurationName="Release")
    project_config = configs("project", {"IPHONEOS_DEPLOYMENT_TARGET": "16.0", "SDKROOT": "iphoneos", "SWIFT_VERSION": "5.0", "CLANG_ENABLE_MODULES": "YES"})
    target_config = configs("target", {"PRODUCT_NAME": "$(TARGET_NAME)", "PRODUCT_BUNDLE_IDENTIFIER": "edu.rescueswarm.prototype",
        "INFOPLIST_FILE": "App/Info.plist", "CODE_SIGN_STYLE": "Automatic", "TARGETED_DEVICE_FAMILY": "1,2",
        "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator", "GENERATE_INFOPLIST_FILE": "NO"})
    target = add("target", "PBXNativeTarget", name="RescueSwarm", productName="RescueSwarm", productType="com.apple.product-type.application",
                 productReference=product, buildConfigurationList=target_config, buildPhases=[sources, frameworks, resources], buildRules=[], dependencies=[], packageProductDependencies=[library])
    project = add("project", "PBXProject", attributes={"LastUpgradeCheck": "1500"}, buildConfigurationList=project_config,
                  compatibilityVersion="Xcode 14.0", developmentRegion="en", knownRegions=["en", "Base"], mainGroup=group,
                  projectDirPath="", projectRoot="", targets=[target], packageReferences=[package])
    folder = ROOT / "RescueSwarm.xcodeproj"
    folder.mkdir(exist_ok=True)
    # Xcode accepts XML property-list projects as well as OpenStep syntax.
    (folder / "project.pbxproj").write_bytes(plistlib.dumps({"archiveVersion": "1", "classes": {}, "objectVersion": "56", "objects": objects, "rootObject": project}))
    scheme = ET.Element("Scheme", LastUpgradeVersion="1500", version="1.3")
    build = ET.SubElement(scheme, "BuildAction", parallelizeBuildables="YES", buildImplicitDependencies="YES")
    entries = ET.SubElement(build, "BuildActionEntries")
    entry = ET.SubElement(entries, "BuildActionEntry", buildForTesting="YES", buildForRunning="YES", buildForProfiling="YES", buildForArchiving="YES", buildForAnalyzing="YES")
    def reference(parent):
        ET.SubElement(parent, "BuildableReference", BuildableIdentifier="primary", BlueprintIdentifier=target,
                      BuildableName="RescueSwarm.app", BlueprintName="RescueSwarm", ReferencedContainer="container:RescueSwarm.xcodeproj")
    reference(entry)
    launch = ET.SubElement(scheme, "LaunchAction", buildConfiguration="Debug", selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB", selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB", launchStyle="0", useCustomWorkingDirectory="NO", ignoresPersistentStateOnLaunch="NO", debugDocumentVersioning="YES", allowLocationSimulation="YES")
    reference(ET.SubElement(launch, "BuildableProductRunnable", runnableDebuggingMode="0"))
    ET.SubElement(scheme, "AnalyzeAction", buildConfiguration="Debug")
    ET.SubElement(scheme, "ArchiveAction", buildConfiguration="Release", revealArchiveInOrganizer="YES")
    schemes = folder / "xcshareddata/xcschemes"
    schemes.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(scheme).write(schemes/"RescueSwarm.xcscheme", encoding="utf-8", xml_declaration=True)
    payload = b"P6\n2 2\n255\n" + bytes([80])*12
    header = {"type": "task", "task_id": 0, "attempt_id": 1, "image_id": "fixture.ppm",
              "sha256": hashlib.sha256(payload).hexdigest(), "payload_bytes": len(payload)}
    encoded = json.dumps(header).encode()
    fixtures = ROOT / "Tests/RescueSwarmCoreTests/Fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures/"python-task.bin").write_bytes(struct.pack("!I", len(encoded))+encoded+payload)
    print("Prepared Xcode project, shared scheme and Python wire fixture.")


if __name__ == "__main__":
    prepare()
