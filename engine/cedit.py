# edit(path, old, new, n=1): exact replace in a CRLF source file, keeping its line endings
def edit(path, old, new, n=1):
    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    s = raw.decode("latin-1").replace("\r\n", "\n")
    c = s.count(old)
    assert c == n, "%s: found %d times (want %d): %r" % (path, c, n, old[:80])
    s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    open(path, "wb").write(s.encode("latin-1"))
