import asyncio
import json
from typing import Any

import discord
from redis import Redis, RedisError

from core.log_modules import log_application
from modules.redis_module import RedisConnector
from settings.config import settings

logger = log_application(__name__)

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
redis_connector = RedisConnector()

REDIS_STATUS_KEY = "youtube_download_statuses"
previous_status: dict = {}


async def fetch_statuses(conn: Redis) -> dict:
    """Redisから全タスクの状態を取得"""
    try:
        return conn.hgetall(REDIS_STATUS_KEY)  # type: ignore[return-value]
    except RedisError:
        logger.exception("Redisから状態取得失敗")
        return {}


def parse_status(status_json: str, task_id: str) -> dict | None:
    """JSONデコード&エラーハンドリング"""
    try:
        result = json.loads(status_json)
    except json.JSONDecodeError:
        logger.exception("タスク%sのJSONデコード失敗", task_id)
        return None
    return result if isinstance(result, dict) else None


def generate_message(status: str, title: str, task_id: str, error: str | None = None) -> str:
    """状態ごとの通知メッセージ生成"""
    if status == "processing":
        return f"【ダウンロード開始】\nタイトル: {title}\nタスクID: `{task_id}`"
    if status == "done":
        return f"【ダウンロード完了】\nタイトル: {title}\nタスクID: `{task_id}`"
    if status == "error":
        return f"【エラー発生】\nタイトル: {title}\nタスクID: `{task_id}`\nエラー内容: {error}"
    return f"【状態更新】\nタイトル: {title}\nタスクID: `{task_id}`\n状態: {status}"


async def notify_discord(channel: discord.abc.Messageable, msg: str) -> None:
    """Discord通知"""
    try:
        await channel.send(msg)
    except discord.DiscordException:
        logger.exception("Discord通知失敗")


def cleanup_task(conn: Redis, task_id: str) -> None:
    """完了・エラー時のRedis/メモリからの削除"""
    try:
        conn.hdel(REDIS_STATUS_KEY, task_id)
        previous_status.pop(task_id, None)
        logger.info("タスク %s をRedisから削除しました", task_id)
    except RedisError:
        logger.exception("タスク %s の削除失敗", task_id)


async def monitor_redis() -> None:
    await client.wait_until_ready()
    conn = redis_connector.get_connection()
    channel = client.get_channel(settings.discord_channel_id)

    if channel is None:
        logger.error("Discordチャンネルが見つかりません。IDを確認してください。")
        return

    if not isinstance(channel, discord.abc.Messageable):
        logger.warning("sendできないチャンネル型: %s", type(channel))
        return

    logger.info("Redis監視タスクを開始します。")
    while not client.is_closed():
        try:
            statuses = await fetch_statuses(conn)
            for task_id, status_json in statuses.items():
                status_data = parse_status(status_json, task_id)
                if not status_data:
                    continue

                status: Any = status_data.get("status")
                title: Any = status_data.get("title", "タイトル取得中")
                error: Any = status_data.get("error")
                prev = previous_status.get(task_id)

                # ステータス変化時のみ通知
                if prev != status:
                    msg = generate_message(status, title, task_id, error)
                    await notify_discord(channel, msg)
                    logger.info("タスク %s の状態が %s → %s に変化", task_id, prev, status)
                    previous_status[task_id] = status

                    # done/errorになったら通知後にRedisから削除
                    if status in ("done", "error"):
                        cleanup_task(conn, task_id)

            # タスクが消えた場合のクリーンアップ
            for task_id in set(previous_status) - set(statuses):
                previous_status.pop(task_id)
        except Exception:
            # 想定外のエラーで監視ループ自体が止まらないよう、意図的に広く捕捉する。
            logger.exception("Redis監視中にエラー")
        await asyncio.sleep(settings.poll_interval_seconds)


@client.event
async def on_ready() -> None:
    logger.info("Discord Botにログインしました。")
    try:
        conn = redis_connector.get_connection()
        pong = conn.ping()
        logger.info("Redis接続確認: %s", pong)
    except RedisError:
        logger.exception("Redis接続失敗")
    client.loop.create_task(monitor_redis())


client.run(settings.discord_token)
