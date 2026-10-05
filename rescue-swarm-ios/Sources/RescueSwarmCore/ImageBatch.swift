import Foundation

/// File-backed imports: a failed selection leaves the previous batch intact.
public struct ImageBatch {
    public struct Item {
        public let imageID: String
        public let url: URL
        public let byteCount: Int
    }
    public let directory: URL
    public let items: [Item]

    public static func copy(_ sources: [URL], into root: URL) throws -> ImageBatch {
        guard !sources.isEmpty, sources.count <= 500 else { throw WireError.invalidPayload }
        let fm = FileManager.default
        let folder = root.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true)
        do {
            var items: [Item] = []
            for (index, source) in sources.enumerated() {
                let values = try source.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
                guard values.isRegularFile == true, let size = values.fileSize,
                      size > 0, size <= Wire.maxPayload else { throw WireError.invalidPayload }
                // Original name remains visible, prefix prevents collisions across folders.
                let name = String(format: "%04d-", index) + source.lastPathComponent
                let target = folder.appendingPathComponent(name)
                try fm.copyItem(at: source, to: target)
                let copiedSize = try target.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard copiedSize > 0, copiedSize <= Wire.maxPayload else { throw WireError.invalidPayload }
                items.append(Item(imageID: name, url: target, byteCount: copiedSize))
            }
            return ImageBatch(directory: folder, items: items)
        } catch {
            try? fm.removeItem(at: folder)
            throw error
        }
    }
    public func read(_ index: Int) throws -> Data {
        guard items.indices.contains(index) else { throw WireError.invalidPayload }
        let item = items[index]
        let size = try item.url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size == item.byteCount, size > 0, size <= Wire.maxPayload else { throw WireError.invalidPayload }
        let bytes = try Data(contentsOf: item.url)
        guard bytes.count == item.byteCount else { throw WireError.invalidPayload }
        return bytes
    }
}
