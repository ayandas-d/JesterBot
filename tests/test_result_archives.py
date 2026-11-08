"""Lossless raw-result rotation keeps evidence readable and protects originals."""

import gzip
import json

import pytest

from tools.result_io import read_result, archive_result


def test_archive_round_trip_preserves_json_and_original_bytes(tmp_path):
    path=tmp_path/"result.json"
    original='{"numbers": [1, 2, 3], "verdict": "CHOP"}\n'
    path.write_text(original)
    destination=archive_result(path)
    assert not path.exists()
    assert gzip.decompress(destination.read_bytes())==original.encode()
    assert read_result(path)==json.loads(original)
    assert read_result(destination)==json.loads(original)


def test_existing_conflicting_archive_never_removes_original(tmp_path):
    path=tmp_path/"result.json";path.write_text('{"original":true}')
    path.with_suffix(".json.gz").write_bytes(gzip.compress(b'{"different":true}'))
    with pytest.raises(ValueError):archive_result(path)
    assert path.exists() and read_result(path)=={"original":True}
