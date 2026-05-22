"""Operator CLI: `tuya-core serve|discover|list`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from tuya_core.cli import app

runner = CliRunner()


def test_serve_invokes_uvicorn_with_bound_host_port(monkeypatch) -> None:
    for k in list(__import__("os").environ):
        if k.startswith("TUYA_"):
            monkeypatch.delenv(k, raising=False)
    with patch("tuya_core.cli.uvicorn.run") as mock_run:
        result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8768


def test_serve_bind_override(monkeypatch) -> None:
    for k in list(__import__("os").environ):
        if k.startswith("TUYA_"):
            monkeypatch.delenv(k, raising=False)
    with patch("tuya_core.cli.uvicorn.run") as mock_run:
        result = runner.invoke(app, ["serve", "--bind", "127.0.0.1:9999"])
    assert result.exit_code == 0
    _, kwargs = mock_run.call_args
    assert kwargs["port"] == 9999


def test_list_prints_daemon_response(monkeypatch) -> None:
    for k in list(__import__("os").environ):
        if k.startswith("TUYA_"):
            monkeypatch.delenv(k, raising=False)

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"bulbs": [{"mac": "aabbccddeeff", "protocol": "tuya"}]}
    fake_resp.raise_for_status.return_value = None

    class FakeAsyncClient:
        def __init__(self, *a, **kw) -> None: ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a) -> None: ...
        async def get(self, url): return fake_resp

    with patch("tuya_core.cli.httpx.AsyncClient", FakeAsyncClient):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "aabbccddeeff" in result.stdout
