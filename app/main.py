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
# タスクごとに最後に通知した状態を保持するハッシュ。プロセスメモリ(前バージョンの
# previous_status)ではなくRedis側に持たせることで、botの再起動やレプリカの重複起動を
# 挟んでも同じ状態変化を二重に通知しないようにしている。
REDIS_NOTIFIED_KEY = "youtube_download_notified_statuses"


async def fetch_statuses(conn: Redis) -> dict:
    """Redisから全タスクの状態を取得"""
    try:
        return conn.hgetall(REDIS_STATUS_KEY)  # type: ignore[return-value]
    except RedisError:
        logger.exception("Redisから状態取得失敗")
        return {}


async def fetch_notified_statuses(conn: Redis) -> dict:
    """タスクごとに最後に通知済みの状態をRedisから取得"""
    try:
        return conn.hgetall(REDIS_NOTIFIED_KEY)  # type: ignore[return-value]
    except RedisError:
        logger.exception("通知済み状態の取得失敗")
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
    """完了・エラー時のRedisからの削除。

    通知済み状態(REDIS_NOTIFIED_KEY)はここでは消さない。消す前にプロセスが落ちると
    次回起動時に再通知されてしまうため、あえて消さずに残し、後続のポーリングで
    タスク自体(REDIS_STATUS_KEY側)が消えたことを検知してから片付ける
    (monitor_redis内の「タスクが消えた場合のクリーンアップ」を参照)。
    """
    try:
        conn.hdel(REDIS_STATUS_KEY, task_id)
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
            notified = await fetch_notified_statuses(conn)
            for task_id, status_json in statuses.items():
                status_data = parse_status(status_json, task_id)
                if not status_data:
                    continue

                status: Any = status_data.get("status")
                title: Any = status_data.get("title", "タイトル取得中")
                error: Any = status_data.get("error")
                prev = notified.get(task_id)

                # ステータス変化時のみ通知
                if prev != status:
                    msg = generate_message(status, title, task_id, error)
                    await notify_discord(channel, msg)
                    logger.info("タスク %s の状態が %s → %s に変化", task_id, prev, status)
                    conn.hset(REDIS_NOTIFIED_KEY, task_id, status)

                # done/errorは通知済みかどうかに関わらず毎回削除を試みる(hdelは冪等なので、
                # 前回削除に失敗して残っていた場合の再試行にもなる)。
                if status in ("done", "error"):
                    cleanup_task(conn, task_id)

            # タスク自体がRedisから消えた(削除完了 or home-api側の一括クリア等)場合、
            # 通知済み状態も追従して片付ける。
            for task_id in set(notified) - set(statuses):
                conn.hdel(REDIS_NOTIFIED_KEY, task_id)
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
