import base64
import hashlib

import pytest

from radiobooth import qr, web


def test_finder_patterns_and_size():
    m = qr.matrix("https://my.radiobooth.fm/")
    assert len(m) == 25  # version 2
    corner = [row[:7] for row in m[:7]]
    assert corner[0] == [True] * 7 and corner[1] == [True] + [False] * 5 + [True]
    assert corner[3] == [True, False, True, True, True, False, True]
    assert m[7][:8] == [False] * 8  # separator


def test_versions_grow_with_length_and_stop_at_ten():
    assert len(qr.matrix("x" * 120)) == 4 * 7 + 17
    assert len(qr.matrix("x" * 213)) == 4 * 10 + 17
    with pytest.raises(ValueError):
        qr.matrix("x" * 214)


def test_known_matrix_is_unchanged():
    # Checked once by scanning it with zxing (versions 1 to 10 all scanned): this pins that output.
    m = qr.matrix("https://my.radiobooth.fm/")
    bits = "".join("1" if d else "0" for row in m for d in row)
    assert hashlib.sha256(bits.encode()).hexdigest() == (
        "d47b54688bb71db58d50d5199699b709ba8607411bbf8fbad8ad10719d950238"
    )


def test_phone_qr_for_web_addresses_only():
    url = web.phone_qr("https://my.radiobooth.fm")
    assert url.startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(url.split(",", 1)[1]).decode()
    assert svg.startswith("<svg") and "<script" not in svg
    assert web.phone_qr("javascript:alert(1)") is None
    assert web.phone_qr("https://example.com/" + "x" * 300) is None
