import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
from redis import RedisError

import main


class TestGenerateMessage:
    def test_processing(self) -> None:
        msg = main.generate_message("processing", "サンプル動画", "task-1")
        assert "ダウンロード開始" in msg
        assert "サンプル動画" in msg
        assert "task-1" in msg

    def test_done(self) -> None:
        msg = main.generate_message("done", "サンプル動画", "task-1")
        assert "ダウンロード完了" in msg

    def test_error_includes_error_message(self) -> None:
        msg = main.generate_message("error", "サンプル動画", "task-1", error="timeout")
        assert "エラー発生" in msg
        assert "timeout" in msg

    def test_unknown_status_falls_back_to_generic_message(self) -> None:
        msg = main.generate_message("queued", "サンプル動画", "task-1")
        assert "状態更新" in msg
        assert "queued" in msg


class TestParseStatus:
    def test_valid_json_object_is_returned_as_dict(self) -> None:
        assert main.parse_status('{"status": "done"}', "task-1") == {"status": "done"}

    def test_invalid_json_returns_none(self) -> None:
        assert main.parse_status("not-json", "task-1") is None

    def test_valid_json_non_object_returns_none(self) -> None:
        assert main.parse_status("[1, 2, 3]", "task-1") is None


class TestFetchStatuses:
    def test_returns_status_hash(self) -> None:
        conn = MagicMock()
        conn.hgetall.return_value = {"task-1": '{"status": "done"}'}

        result = asyncio.run(main.fetch_statuses(conn))

        assert result == {"task-1": '{"status": "done"}'}
        conn.hgetall.assert_called_once_with(main.REDIS_STATUS_KEY)

    def test_redis_error_returns_empty_dict(self) -> None:
        conn = MagicMock()
        conn.hgetall.side_effect = RedisError("boom")

        result = asyncio.run(main.fetch_statuses(conn))

        assert result == {}


class TestFetchNotifiedStatuses:
    def test_returns_notified_hash(self) -> None:
        conn = MagicMock()
        conn.hgetall.return_value = {"task-1": "done"}

        result = asyncio.run(main.fetch_notified_statuses(conn))

        assert result == {"task-1": "done"}
        conn.hgetall.assert_called_once_with(main.REDIS_NOTIFIED_KEY)

    def test_redis_error_returns_empty_dict(self) -> None:
        conn = MagicMock()
        conn.hgetall.side_effect = RedisError("boom")

        result = asyncio.run(main.fetch_notified_statuses(conn))

        assert result == {}


class TestNotifyDiscord:
    def test_sends_message_to_channel(self) -> None:
        channel = MagicMock()
        channel.send = AsyncMock()

        asyncio.run(main.notify_discord(channel, "hello"))

        channel.send.assert_awaited_once_with("hello")

    def test_discord_exception_does_not_propagate(self) -> None:
        channel = MagicMock()
        channel.send = AsyncMock(side_effect=discord.DiscordException("boom"))

        asyncio.run(main.notify_discord(channel, "hello"))


class TestCleanupTask:
    def test_deletes_task_from_status_hash(self) -> None:
        conn = MagicMock()

        main.cleanup_task(conn, "task-1")

        conn.hdel.assert_called_once_with(main.REDIS_STATUS_KEY, "task-1")

    def test_redis_error_does_not_propagate(self) -> None:
        conn = MagicMock()
        conn.hdel.side_effect = RedisError("boom")

        main.cleanup_task(conn, "task-1")
