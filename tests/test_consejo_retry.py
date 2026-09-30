"""Chequeo del retry del árbitro en consejo.py, con _post mockeado (sin red). Uso: python3 tests/test_consejo_retry.py"""
import sys, pathlib, http.client, urllib.error, io
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bin"))
import consejo as c
c.time.sleep = lambda s: None

def fake(seq):
    it = iter(seq)
    def _post(*a):
        x = next(it)
        if isinstance(x, Exception): raise x
        return x
    c._post = _post

fake([http.client.RemoteDisconnected("Remote end closed connection without response"), "OK"])
r = c.call_arbitro([]); assert r.startswith("OK") and "tras 1 reintento por RemoteDisconnected" in r, r

fake([urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO()), TimeoutError("timed out"), "OK"])
r = c.call_arbitro([]); assert "tras 2 reintentos" in r, r

fake([urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO()), "OK"])
assert c.call_arbitro([]).startswith("[ERROR"), "401 no debe reintentar"

fake([ValueError("json malo"), "OK"])
assert c.call_arbitro([]).startswith("[ERROR"), "JSON malo no debe reintentar"

fake([urllib.error.URLError("Network is unreachable")] * 3)
assert c.call_arbitro([]).startswith("[ERROR"), "3 fallos -> ERROR"

fake(["OK"]); assert c.call_arbitro([]) == "OK", "path feliz silencioso"
print("retry checks OK")
