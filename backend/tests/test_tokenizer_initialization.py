import os
import subprocess
import sys
from hashlib import sha1
from pathlib import Path

import pytest

from app.modules.competitive_intelligence import document_processing as processing

BACKEND = Path(__file__).resolve().parents[1]


def test_application_import_and_pure_tests_work_with_cold_cache_offline(tmp_path):
    # A subprocess prevents warm tiktoken/module caches from hiding eager imports.
    code = """
import socket
import tiktoken
import pytest
def forbidden(*args, **kwargs):
    raise AssertionError('unexpected tokenizer/network acquisition')
socket.getaddrinfo = forbidden
socket.socket.connect = forbidden
tiktoken.encoding_for_model = forbidden
tiktoken.get_encoding = forbidden
import app.main
from app.scripts.competitive_intelligence_benchmark import benchmark_io
assert benchmark_io.chunking_configuration()['resolved_tokenizer'] == 'cl100k_base'
assert pytest.main(['--collect-only', '-q', '-p', 'no:cacheprovider']) == 0
raise SystemExit(pytest.main([
    '-q', '-p', 'no:cacheprovider', 'tests/test_module_registry.py',
]))
"""
    environment = os.environ.copy()
    environment["TIKTOKEN_CACHE_DIR"] = str(tmp_path / "empty-cache")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_provision_check_reports_missing_assets(tmp_path):
    environment = os.environ.copy()
    environment["TIKTOKEN_CACHE_DIR"] = str(tmp_path / "empty-cache")
    result = subprocess.run(
        [sys.executable, "-m", "app.scripts.provision_tokenizer", "--check"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "Tokenizer assets missing or invalid" in result.stderr


def test_offline_provision_check_preserves_corrupt_cache(tmp_path):
    asset_url = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
    cache_file = tmp_path / sha1(asset_url.encode()).hexdigest()
    cache_file.write_bytes(b"invalid cached asset")
    environment = os.environ.copy()
    environment["TIKTOKEN_CACHE_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "app.scripts.provision_tokenizer", "--check"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "Tokenizer assets missing or invalid" in result.stderr
    assert cache_file.read_bytes() == b"invalid cached asset"


@pytest.mark.parametrize("chunk_size,overlap", [(0, 0), (-1, 0), (4, -1), (4, 4)])
def test_invalid_chunk_parameters_fail_before_tokenizer_loading(monkeypatch, chunk_size, overlap):
    def forbidden():
        raise AssertionError("invalid parameters must not acquire tokenizer assets")

    monkeypatch.setattr(processing, "get_tokenizer", forbidden)
    with pytest.raises(ValueError):
        processing.chunk_document(None, chunk_size=chunk_size, overlap=overlap)


def test_loader_is_lazy_cached_and_uses_the_production_model(monkeypatch):
    processing.get_tokenizer.cache_clear()
    sentinel = object()
    calls = []

    def load(model):
        calls.append(model)
        return sentinel

    monkeypatch.setattr(processing.tiktoken, "encoding_for_model", load)
    try:
        assert calls == []
        assert processing.get_tokenizer() is sentinel
        assert processing.get_tokenizer() is sentinel
        assert calls == ["text-embedding-3-small"]
    finally:
        processing.get_tokenizer.cache_clear()


def test_asset_failure_propagates_and_is_retryable(monkeypatch):
    processing.get_tokenizer.cache_clear()
    failure = OSError("asset unavailable")
    calls = []

    def fail(model):
        calls.append(model)
        raise failure

    monkeypatch.setattr(processing.tiktoken, "encoding_for_model", fail)
    try:
        for _ in range(2):
            with pytest.raises(OSError) as caught:
                processing.get_tokenizer()
            assert caught.value is failure
        assert len(calls) == 2
    finally:
        processing.get_tokenizer.cache_clear()
