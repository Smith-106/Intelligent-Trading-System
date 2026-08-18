"""Coverage completion for KOL OCR pipeline + Discord ingest.

Targets remaining uncovered lines/branches in:
- chart_ocr: is_chart_likely fall-through, download_attachment (mocked
  network), ocr_image all backends (mocked tesseract), process_attachment
  download/OCR branches, enrich_text_with_ocr merge
- discord_ingest: snowflake/ISO timestamp paths, non-dict author,
  attachment loop (mocked process_attachment), OCR merge, side coercion,
  export shapes (list/unsupported), non-dict messages, fetch_channel_history
  (mocked urllib), ingest_channel_poll (mocked fetch)

No real network / no real tesseract: all external calls are mocked.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quantflow.strategy.kol_signals import chart_ocr as ocr_mod
from quantflow.strategy.kol_signals import discord_ingest as di_mod
from quantflow.strategy.kol_signals.chart_ocr import (
    download_attachment,
    enrich_text_with_ocr,
    is_chart_likely,
    ocr_image,
    process_attachment,
)
from quantflow.strategy.kol_signals.discord_ingest import (
    _ms_from_discord_snowflake,
    fetch_channel_history,
    ingest_channel_poll,
    ingest_export_file,
    message_to_signal,
)
from quantflow.strategy.kol_signals.models import AttachmentMeta, SignalSide
from quantflow.strategy.kol_signals.store import KolSignalStore


# ---------------------------------------------------------------------------
# chart_ocr.is_chart_likely
# ---------------------------------------------------------------------------


class TestIsChartLikely:
    def test_image_without_chart_name_falls_through(self) -> None:
        # image ext present, no chart keyword, no discord CDN -> line-32 eval
        assert is_chart_likely(filename="photo.png", content_type="image/png") is False

    def test_chart_name_without_image_ext(self) -> None:
        # no image ext but chart keyword in name -> line-32 eval True
        assert is_chart_likely(filename="tradingview_alert.txt") is True

    def test_discord_cdn_url(self) -> None:
        assert is_chart_likely(url="https://media.discordapp.net/x/y.png") is True


# ---------------------------------------------------------------------------
# chart_ocr.download_attachment (mocked urllib)
# ---------------------------------------------------------------------------


class TestDownloadAttachment:
    def test_no_url_returns_none(self, tmp_path: Path) -> None:
        assert download_attachment("", tmp_path) is None

    def test_success_download(self, tmp_path: Path) -> None:
        resp = MagicMock()
        resp.read.return_value = b"bytes"
        cm = MagicMock()
        cm.__enter__.return_value = resp
        with patch("urllib.request.urlopen", return_value=cm) as mock_open:
            path = download_attachment("https://cdn.example.com/a.png", tmp_path)
        mock_open.assert_called_once()
        assert path is not None
        assert path.read_bytes() == b"bytes"

    def test_sanitizes_filename(self, tmp_path: Path) -> None:
        resp = MagicMock()
        resp.read.return_value = b"x"
        cm = MagicMock()
        cm.__enter__.return_value = resp
        with patch("urllib.request.urlopen", return_value=cm):
            path = download_attachment(
                "https://cdn.example.com/my chart(1).png",
                tmp_path,
                filename="",
            )
        assert path is not None
        assert path.name == "my_chart_1_.png"


# ---------------------------------------------------------------------------
# chart_ocr.ocr_image
# ---------------------------------------------------------------------------


class TestOcrImage:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert ocr_image(tmp_path / "nope.png") == ("", "none")

    def test_backend_none(self, tmp_path: Path) -> None:
        p = tmp_path / "img.png"
        p.write_bytes(b"x")
        assert ocr_image(p, backend="none") == ("", "none")
        assert ocr_image(p, backend="") == ("", "none")

    def test_vision_stub(self, tmp_path: Path) -> None:
        p = tmp_path / "img.png"
        p.write_bytes(b"x")
        assert ocr_image(p, backend="vision_stub") == ("", "vision_stub")

    def test_unknown_backend(self, tmp_path: Path) -> None:
        p = tmp_path / "img.png"
        p.write_bytes(b"x")
        assert ocr_image(p, backend="bogus") == ("", "none")

    def test_auto_backend_import_error(self, tmp_path: Path) -> None:
        # backend=auto + pytesseract missing -> ImportError, skip tesseract
        # warning (line-97 False branch) and return ("", "none")
        p = tmp_path / "img.png"
        p.write_bytes(b"x")
        assert ocr_image(p, backend="auto") == ("", "none")

    def test_tesseract_import_error(self, tmp_path: Path) -> None:
        # pytesseract not installed -> ImportError branch returns ("", "none")
        p = tmp_path / "img.png"
        p.write_bytes(b"x")
        text, used = ocr_image(p, backend="tesseract")
        assert used == "none"

    def test_tesseract_success_mocked(self, tmp_path: Path) -> None:
        from PIL import Image

        img = Image.new("RGB", (4, 4), color="red")
        p = tmp_path / "img.png"
        img.save(p)
        fake_pt = MagicMock()
        fake_pt.image_to_string.return_value = "  BTC/USDT 64000 long  "
        with patch.dict(sys.modules, {"pytesseract": fake_pt}):
            text, used = ocr_image(p, backend="auto")
        assert text == "BTC/USDT 64000 long"
        assert used == "tesseract"


# ---------------------------------------------------------------------------
# chart_ocr.process_attachment + enrich_text_with_ocr
# ---------------------------------------------------------------------------


class TestProcessAttachment:
    def test_download_branch(self, tmp_path: Path) -> None:
        with patch.object(ocr_mod, "download_attachment", return_value=tmp_path / "dl.png"):
            meta = process_attachment(
                url="https://cdn.example.com/a.png",
                content_type="image/png",
                filename="a.png",
                dest_dir=tmp_path,
                ocr_backend="none",
            )
        assert meta.local_path == str(tmp_path / "dl.png")

    def test_download_failure_branch(self, tmp_path: Path) -> None:
        with patch.object(ocr_mod, "download_attachment", return_value=None):
            meta = process_attachment(
                url="https://cdn.example.com/a.png",
                filename="a.png",
                dest_dir=tmp_path,
                ocr_backend="none",
            )
        assert meta.local_path == ""

    def test_ocr_call_branch(self, tmp_path: Path) -> None:
        local = tmp_path / "img.png"
        local.write_bytes(b"x")
        with patch.object(ocr_mod, "ocr_image", return_value=("TEXT", "tesseract")):
            meta = process_attachment(
                local_path=str(local),
                content_type="image/png",
                filename="chart.png",
                ocr_backend="auto",
            )
        assert meta.ocr_text == "TEXT"
        assert meta.ocr_backend == "tesseract"


class TestEnrichTextWithOcr:
    def test_merges_ocr_blobs(self) -> None:
        out = enrich_text_with_ocr(
            "long",
            [AttachmentMeta(ocr_text="BTC/USDT 4h"), AttachmentMeta(ocr_text="")],
        )
        assert out["merged_text"] == "long\nBTC/USDT 4h"
        assert out["ocr_used"] is True
        assert out["symbol"] == "BTC/USDT"

    def test_no_ocr_blobs(self) -> None:
        out = enrich_text_with_ocr("", [AttachmentMeta(ocr_text="")])
        assert out["merged_text"] == ""
        assert out["ocr_used"] is False


# ---------------------------------------------------------------------------
# discord_ingest._ms_from_discord_snowflake
# ---------------------------------------------------------------------------


class TestSnowflake:
    def test_valid_snowflake(self) -> None:
        ts = _ms_from_discord_snowflake("123456789012345678")
        assert ts > 1_420_000_000_000

    def test_invalid_snowflake_falls_back(self) -> None:
        ts = _ms_from_discord_snowflake("not-a-number")
        assert ts > 1_000_000_000_000


# ---------------------------------------------------------------------------
# discord_ingest.message_to_signal paths
# ---------------------------------------------------------------------------


class TestMessageToSignal:
    def test_author_as_string(self) -> None:
        s = message_to_signal(
            {"id": "1", "author": "plain-name", "content": "long", "timestamp_ms": 1},
            source_id="s",
            process_images=False,
        )
        assert s.author == "plain-name"

    def test_iso_timestamp_valid(self) -> None:
        s = message_to_signal(
            {"id": "1", "content": "long", "timestamp": "2023-11-14T22:13:20Z"},
            source_id="s",
            process_images=False,
        )
        assert s.created_at_ms == 1_700_000_000_000

    def test_iso_timestamp_invalid_uses_snowflake(self) -> None:
        s = message_to_signal(
            {"id": "123456789012345678", "content": "long", "timestamp": "not-a-date"},
            source_id="s",
            process_images=False,
        )
        assert s.created_at_ms == _ms_from_discord_snowflake("123456789012345678")

    def test_non_str_iso_uses_snowflake(self) -> None:
        s = message_to_signal(
            {"id": "123456789012345678", "content": "long", "timestamp": 123456},
            source_id="s",
            process_images=False,
        )
        assert s.created_at_ms == _ms_from_discord_snowflake("123456789012345678")

    def test_no_timestamp_no_id_uses_now(self) -> None:
        s = message_to_signal({"content": "long"}, source_id="s", process_images=False)
        assert s.created_at_ms > 1_000_000_000_000

    def test_attachment_loop_skips_non_dict(self) -> None:
        with patch.object(
            di_mod,
            "process_attachment",
            return_value=AttachmentMeta(url="u", local_path="p", ocr_text=""),
        ) as mock_pa:
            s = message_to_signal(
                {
                    "id": "1",
                    "content": "long",
                    "timestamp_ms": 1,
                    "attachments": ["not-a-dict", {"url": "u", "filename": "f.png"}],
                },
                source_id="s",
                process_images=True,
                ocr_backend="none",
            )
        assert mock_pa.call_count == 1
        assert len(s.attachments) == 1

    def test_ocr_merge_prefers_enriched(self) -> None:
        enriched = {
            "side": SignalSide.LONG,
            "symbol": "BTC/USDT",
            "entry": 64000.0,
            "stop_loss": None,
            "take_profit": [],
            "timeframe": "4h",
            "confidence": 0.95,
            "parse_notes": [],
            "ocr_used": True,
        }
        with patch.object(di_mod, "process_attachment", return_value=AttachmentMeta(ocr_text="t")):
            with patch.object(di_mod, "enrich_text_with_ocr", return_value=enriched):
                s = message_to_signal(
                    {
                        "id": "1",
                        "content": "long",
                        "timestamp_ms": 1,
                        "attachments": [{"url": "u", "filename": "f.png"}],
                    },
                    source_id="s",
                    process_images=True,
                    ocr_backend="auto",
                )
        assert s.symbol == "BTC/USDT"
        assert "ocr_merged" in s.parse_notes

    def test_ocr_merge_without_ocr_used(self) -> None:
        enriched = {
            "side": SignalSide.LONG,
            "symbol": "BTC/USDT",
            "confidence": 0.9,
            "parse_notes": [],
            "ocr_used": False,
        }
        with patch.object(di_mod, "process_attachment", return_value=AttachmentMeta(ocr_text="t")):
            with patch.object(di_mod, "enrich_text_with_ocr", return_value=enriched):
                s = message_to_signal(
                    {
                        "id": "1",
                        "content": "long",
                        "timestamp_ms": 1,
                        "attachments": [{"url": "u", "filename": "f.png"}],
                    },
                    source_id="s",
                    process_images=True,
                    ocr_backend="auto",
                )
        assert "ocr_merged" not in s.parse_notes

    def test_ocr_merge_prefers_original_when_enriched_weaker(self) -> None:
        # enriched confidence < parsed confidence -> keep parsed (114 False)
        enriched = {
            "side": SignalSide.LONG,
            "symbol": "",
            "entry": None,
            "stop_loss": None,
            "take_profit": [],
            "timeframe": "",
            "confidence": 0.1,
            "parse_notes": [],
            "ocr_used": True,
        }
        with patch.object(di_mod, "process_attachment", return_value=AttachmentMeta(ocr_text="t")):
            with patch.object(di_mod, "enrich_text_with_ocr", return_value=enriched):
                s = message_to_signal(
                    {
                        "id": "1",
                        "content": "long BTC/USDT entry 1000",
                        "timestamp_ms": 1,
                        "attachments": [{"url": "u", "filename": "f.png"}],
                    },
                    source_id="s",
                    process_images=True,
                    ocr_backend="auto",
                )
        # parsed confidence ~0.89 > enriched 0.1 -> original parse retained
        assert s.symbol == "BTC/USDT"

        # original parse kept (confidence ~0.53 >= 0.1 comparison fails)
        assert s.symbol == "BTC/USDT"

    def test_side_string_coercion(self) -> None:
        # parse_trade_text returns string side -> coerced to SignalSide
        with patch.object(
            di_mod,
            "parse_trade_text",
            return_value={
                "side": "short",
                "symbol": "ETH/USDT",
                "entry": None,
                "stop_loss": None,
                "take_profit": [],
                "timeframe": "",
                "confidence": 0.8,
                "parse_notes": [],
            },
        ):
            s = message_to_signal(
                {"id": "1", "content": "x", "timestamp_ms": 1},
                source_id="s",
                process_images=False,
            )
        assert s.side == SignalSide.SHORT

    def test_side_unparseable_string_falls_back_unknown(self) -> None:
        with patch.object(
            di_mod,
            "parse_trade_text",
            return_value={
                "side": "bogus-side",
                "symbol": "",
                "entry": None,
                "stop_loss": None,
                "take_profit": [],
                "timeframe": "",
                "confidence": 0.0,
                "parse_notes": [],
            },
        ):
            s = message_to_signal(
                {"id": "1", "content": "x", "timestamp_ms": 1},
                source_id="s",
                process_images=False,
            )
        assert s.side == SignalSide.UNKNOWN


# ---------------------------------------------------------------------------
# discord_ingest.ingest_export_file shapes
# ---------------------------------------------------------------------------


class TestIngestExportFile:
    def _export(self, tmp_path: Path, data) -> Path:
        p = tmp_path / "export.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_list_shape(self, tmp_path: Path) -> None:
        p = self._export(
            tmp_path,
            [{"id": "1", "content": "long BTC", "timestamp_ms": 1}],
        )
        store = KolSignalStore(tmp_path / "st")
        out = ingest_export_file(p, store=store, process_images=False, ocr_backend="none")
        assert out["ingested"] == 1

    def test_unsupported_shape(self, tmp_path: Path) -> None:
        p = self._export(tmp_path, "just-a-string")
        out = ingest_export_file(p, store=KolSignalStore(tmp_path / "st2"))
        assert out["error"] == "unsupported_export_shape"

    def test_non_dict_messages_skipped(self, tmp_path: Path) -> None:
        p = self._export(
            tmp_path,
            {
                "channel_id": "ch9",
                "messages": ["nope", {"id": "2", "content": "long", "timestamp_ms": 1}],
            },
        )
        store = KolSignalStore(tmp_path / "st3")
        out = ingest_export_file(p, store=store, process_images=False, ocr_backend="none")
        assert out["ingested"] == 1
        assert out["skipped"] == 1


# ---------------------------------------------------------------------------
# discord_ingest.fetch_channel_history (mocked urllib)
# ---------------------------------------------------------------------------


class TestFetchChannelHistory:
    def test_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="DISCORD_BOT_TOKEN"):
            fetch_channel_history("ch1")

    def test_success_payload(self) -> None:
        payload = [{"id": "1", "content": "long"}]
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        cm = MagicMock()
        cm.__enter__.return_value = resp
        with patch("urllib.request.urlopen", return_value=cm) as mock_open:
            out = fetch_channel_history("ch1", token="tok", before="999", limit=50)
        assert len(out) == 1
        assert out[0]["channel_id"] == "ch1"
        mock_open.assert_called_once()

    def test_payload_with_existing_channel_id(self) -> None:
        # message dict already carries channel_id -> 253 False branch
        payload = [{"id": "1", "content": "long", "channel_id": "already"}]
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        cm = MagicMock()
        cm.__enter__.return_value = resp
        with patch("urllib.request.urlopen", return_value=cm):
            out = fetch_channel_history("ch1", token="tok")
        assert out[0]["channel_id"] == "already"

    def test_non_list_payload_returns_empty(self) -> None:
        resp = MagicMock()
        resp.read.return_value = b'{"ok": true}'
        cm = MagicMock()
        cm.__enter__.return_value = resp
        with patch("urllib.request.urlopen", return_value=cm):
            assert fetch_channel_history("ch1", token="tok") == []

    def test_http_error_raises(self) -> None:
        err = urllib.error.HTTPError(
            "https://discord.com/api/v10/channels/ch1/messages",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b"rate limited"),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(RuntimeError, match="Discord API 429"):
                fetch_channel_history("ch1", token="tok")


# ---------------------------------------------------------------------------
# discord_ingest.ingest_channel_poll (mocked fetch)
# ---------------------------------------------------------------------------


class TestIngestChannelPoll:
    def test_poll_with_registry_source(self, tmp_path: Path) -> None:
        reg = tmp_path / "reg.yaml"
        reg.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "source_id": "paid_kol",
                            "channel_ids": ["ch77"],
                            "weight": 1.5,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        messages = [
            {"id": "m1", "content": "long BTC", "timestamp_ms": 1},
            {"id": "m1", "content": "long BTC", "timestamp_ms": 1},  # dedupe
        ]
        store = KolSignalStore(tmp_path / "st")
        with patch.object(di_mod, "fetch_channel_history", return_value=messages):
            out = ingest_channel_poll(
                "ch77",
                registry_path=reg,
                store=store,
                process_images=False,
                ocr_backend="none",
                token="tok",
            )
        assert out["ingested"] == 1
        assert out["skipped"] == 1
        assert out["source_id"] == "paid_kol"

    def test_poll_without_registry_source(self, tmp_path: Path) -> None:
        store = KolSignalStore(tmp_path / "st")
        with patch.object(di_mod, "fetch_channel_history", return_value=[]):
            out = ingest_channel_poll(
                "ch88",
                store=store,
                process_images=False,
                ocr_backend="none",
                token="tok",
            )
        assert out["ingested"] == 0
        assert out["source_id"] == "discord:ch88"
