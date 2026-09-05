import QtQuick
import QtTest
import "../OutputBuffer.js" as Buffer

TestCase {
    name: "OutputBuffer"

    function test_unterminated_line_limit() {
        var b = Buffer.create(16, true)
        var lines = []
        var onLine = function (line) { lines.push(line) }
        verify(Buffer.append(b, "x".repeat(16), onLine))
        compare(b.pending.length, 16)
        verify(!Buffer.append(b, "x", onLine))
        compare(b.pending, "")
        verify(!Buffer.append(b, "\n", onLine))
        Buffer.finish(b, onLine)
        compare(lines.length, 0)
    }

    function test_chunked_protocol_and_final_line() {
        var b = Buffer.create(32, true)
        var lines = []
        var onLine = function (line) { lines.push(line) }
        for (var chunk of ["ab", "c\nd", "\n\ntail"])
            verify(Buffer.append(b, chunk, onLine))
        compare(lines, ["abc", "d", ""])
        Buffer.finish(b, onLine)
        compare(lines, ["abc", "d", "", "tail"])
        compare(b.pending, "")
    }

    function test_limits_include_consumed_lines_and_delimiters() {
        var b = Buffer.create(4, true)
        verify(Buffer.append(b, "a\nb\n"))
        compare(b.pending, "")
        verify(!Buffer.append(b, "\n"))
    }

    function test_utf8_budget() {
        compare(Buffer.utf8Bytes("aé界😀"), 10)
        var b = Buffer.create(10, false)
        verify(Buffer.append(b, "aé界😀"))
        verify(!Buffer.append(b, "x"))
        compare(b.text, "aé界😀")
    }
}
