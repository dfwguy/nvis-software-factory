# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual property and proprietary
# rights in and to this material, related documentation and any modifications thereto. Any use,
# reproduction, disclosure or distribution of this material and related documentation without an
# express license agreement from NVIDIA CORPORATION or its affiliates is strictly prohibited.

"""A compressed response must arrive whole.

These tests exist because of a bug that made the application completely unusable in a browser
while every check we had said it was fine.

Request teardown reset a ``contextvars.Token``, and a token may be reset exactly once. For a
streaming response Flask holds the request context open until the body generator drains, so
teardown ran twice and the second reset raised. By then the status line and the entire payload had
already gone out, so no error handler could turn it into a 500 -- the server could only drop the
connection. Chunked responses lost their terminating chunk, and browsers correctly discard a body
they cannot prove is complete: ``ERR_INCOMPLETE_CHUNKED_ENCODING`` on every JavaScript bundle, and
a blank page.

Two properties of that bug explain the shape of these tests.

It was invisible to the Flask test client, which consumes the WSGI iterable in-process and never
frames a body at all. So these tests run a real HTTP server and read from a real socket.

It only appeared when the client offered ``Accept-Encoding``, because that is what selects the
streaming compressor. Plain ``curl`` -- and every manual check performed while building the
deployment -- sends no such header and saw a perfect response. Browsers always send it.

Two details of the harness are load-bearing, and both were got wrong on the first attempt in ways
that made these tests pass against the broken code:

**The server must speak HTTP/1.1.** Under HTTP/1.0 a body with no ``Content-Length`` ends when the
connection closes, so a truncated response is byte-for-byte indistinguishable from a complete one
and there is nothing for a client to detect. Chunked encoding is the entire mechanism by which
this bug is observable -- the missing terminator is the symptom.

**Decompressing the body is not a sufficient assertion.** A brotli stream that lost only its
terminator still decompresses, and returns every original byte. The truncated real bundle did
exactly that. So these tests assert on *transport framing*: ``http.client`` raises
``IncompleteRead`` when a chunked body ends without its terminator, and that exception -- not a
content comparison -- is what fails when the bug is present.
"""

from __future__ import annotations

import http.client
import threading
from pathlib import Path

import brotli
import pytest
from werkzeug.serving import WSGIRequestHandler, make_server

# Deliberately not trivially compressible. A body of one repeated token collapses to a few dozen
# bytes, emerges from the compressor in a single chunk, and so never exercises multi-chunk
# streaming -- which is the path that breaks.
_ASSET_BODY = (
    b"// streaming regression fixture\n"
    + b"".join(
        b"export const k%d = '%s';\n" % (i, (b"%08x" % (i * 2654435761 % 0xFFFFFFFF)) * 4)
        for i in range(2000)
    )
)


class _Handler(WSGIRequestHandler):
    """HTTP/1.1 so that a body without Content-Length is chunked, and quiet so that the
    per-request log lines do not bury the assertion output."""

    protocol_version = "HTTP/1.1"

    def log_request(self, *_args, **_kwargs) -> None:
        return


@pytest.fixture
def asset(_app_module) -> str:
    """A real file under the SPA asset directory, served by the real route.

    Written rather than assumed: the frontend is built by a later CI stage and by the Docker
    image, so ``static/spa/assets`` is usually absent when this suite runs. Depending on build
    output would make the test skip precisely in the pipeline that most needs it.
    """
    import paths

    directory = Path(paths.SPA_DIR) / "assets"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "streaming-regression-fixture.js"
    target.write_bytes(_ASSET_BODY)
    try:
        yield target.name
    finally:
        target.unlink(missing_ok=True)


@pytest.fixture
def server(_app_module):
    """The application behind a real socket, on an ephemeral port."""
    httpd = make_server(
        "127.0.0.1", 0, _app_module.app, threaded=True, request_handler=_Handler,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[:2]
    finally:
        httpd.shutdown()
        thread.join(timeout=10)
        httpd.server_close()


def _fetch(address, path: str, encoding: str) -> tuple[int, dict[str, str], bytes]:
    """One request, reading the body to completion.

    ``response.read()`` is where the bug surfaces: on a chunked body that never sent its
    terminator it raises ``http.client.IncompleteRead``. That is allowed to propagate. Catching it
    and returning what arrived would recreate the blind spot these tests exist to close.
    """
    host, port = address
    conn = http.client.HTTPConnection(host, port, timeout=30)
    try:
        conn.request("GET", path, headers={"Accept-Encoding": encoding})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def _decode(applied: str | None, body: bytes) -> bytes:
    """Undo whatever encoding the server chose.

    Note that this is not the safety net -- a stream missing only its terminator decompresses
    perfectly well. ``_fetch`` raising IncompleteRead is what catches the regression; this just
    lets one assertion cover every algorithm.
    """
    import gzip
    import zlib

    if applied == "br":
        return brotli.decompress(body)
    if applied == "gzip":
        return gzip.decompress(body)
    if applied == "deflate":
        return zlib.decompress(body)
    assert applied is None, f"unexpected Content-Encoding {applied!r}"
    return body


@pytest.mark.parametrize("encoding", ["br", "gzip", "deflate", "gzip, deflate, br"])
def test_an_asset_arrives_whole_under_every_encoding_a_browser_offers(server, asset, encoding):
    """The regression, stated directly.

    Parametrized over the encodings rather than pinned to brotli because the choice among them is
    the client's and the library's, not ours. A fix that repaired only the one algorithm we
    happened to reproduce would leave the bug live for the next browser that reorders its
    Accept-Encoding header.
    """
    status, headers, body = _fetch(server, f"/assets/{asset}", encoding)

    assert status == 200
    assert _decode(headers.get("Content-Encoding"), body) == _ASSET_BODY


def test_the_uncompressed_path_still_works(server, asset):
    """The control. If this fails too, the problem is not compression."""
    status, _headers, body = _fetch(server, f"/assets/{asset}", "identity")

    assert status == 200
    assert body == _ASSET_BODY


def test_teardown_runs_clean_for_a_streamed_response(server, asset, caplog):
    """No exception escapes while the body is being written.

    The truncation was the visible symptom; this is the cause. Asserted separately so that if a
    future change reintroduces a raising teardown, the failure names the reason rather than
    leaving someone to rediscover it from a byte count.
    """
    import logging

    with caplog.at_level(logging.ERROR):
        status, _headers, _body = _fetch(server, f"/assets/{asset}", "br")

    assert status == 200
    offenders = [r for r in caplog.records if "has already been used once" in r.getMessage()]
    assert not offenders, "a contextvars Token was reset twice during teardown"


def test_a_second_request_on_the_same_connection_is_also_whole(server, asset):
    """Keep-alive, which is how a browser fetches forty bundles.

    A teardown that corrupts context state tends to fail on the *second* request through a worker
    rather than the first, so a suite that only ever opens fresh connections can miss it.
    """
    host, port = server
    conn = http.client.HTTPConnection(host, port, timeout=30)
    try:
        bodies = []
        for _ in range(3):
            conn.request("GET", f"/assets/{asset}", headers={"Accept-Encoding": "br"})
            response = conn.getresponse()
            raw = response.read()
            assert response.status == 200
            bodies.append(_decode(response.getheader("Content-Encoding"), raw))
    finally:
        conn.close()

    assert bodies == [_ASSET_BODY] * 3


def test_a_large_api_payload_arrives_whole(server):
    """The contract bundle is the biggest thing the API returns and the most likely to stream.

    It is also the endpoint whose entire purpose is to be handed to another team's agent, so a
    body that is truncated but decodes far enough to look plausible would be an unusually
    expensive failure.
    """
    import json

    status, headers, body = _fetch(server, "/api/contracts/bundle", "br")

    assert status == 200
    decoded = _decode(headers.get("Content-Encoding"), body)
    parsed = json.loads(decoded)
    assert parsed, "a truncated JSON body would fail to parse here"
