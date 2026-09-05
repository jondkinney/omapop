.pragma library

// SplitParser must deliver chunks immediately (splitMarker: ""). Waiting for
// a delimiter there lets an unterminated line grow before this limit runs.
function create(limit, lineMode) {
    return { limit: limit, lineMode: lineMode, bytes: 0, text: "", pending: "", overflow: false }
}

function utf8Bytes(text) {
    var bytes = 0
    for (var i = 0; i < text.length; i++) {
        var code = text.charCodeAt(i)
        if (code < 0x80) bytes++
        else if (code < 0x800) bytes += 2
        else if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length
                 && text.charCodeAt(i + 1) >= 0xdc00 && text.charCodeAt(i + 1) <= 0xdfff) {
            bytes += 4
            i++
        } else bytes += 3
    }
    return bytes
}

function append(buffer, data, onLine) {
    if (buffer.overflow) return false
    buffer.bytes += utf8Bytes(data)
    if (buffer.bytes > buffer.limit) {
        buffer.bytes = buffer.limit + 1
        buffer.overflow = true
        buffer.pending = ""
        return false
    }
    if (!buffer.lineMode) {
        buffer.text += data
        return true
    }
    buffer.pending += data
    var end
    while ((end = buffer.pending.indexOf("\n")) !== -1) {
        var line = buffer.pending.slice(0, end)
        buffer.pending = buffer.pending.slice(end + 1)
        if (typeof onLine === "function") onLine(line)
    }
    return true
}

function finish(buffer, onLine) {
    if (!buffer.overflow && buffer.pending && typeof onLine === "function")
        onLine(buffer.pending)
    buffer.pending = ""
}
