import asyncio
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

import aiohttp
import websockets
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from websockets.exceptions import ConnectionClosed


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tg-userbot")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_NAME = os.getenv("TG_SESSION") or os.getenv("SESSION_NAME", "userbot")
SESSION_STRING = os.getenv("SESSION_STRING")
BACKEND_HTTP_BASE = os.getenv("BACKEND_HTTP_BASE", "http://backend:7485").rstrip("/")
BACKEND_WS_BASE = os.getenv("BACKEND_WS_BASE", "ws://backend:7485").rstrip("/")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", ".")
INPUT_TIMEOUT_SECONDS = int(os.getenv("INPUT_TIMEOUT_SECONDS", "120"))
TG_PROXY = os.getenv("TG_PROXY", "").strip()

DIRECTIVE_RE = re.compile(r"\{(?P<action>[a-zA-Z_][a-zA-Z0-9_]*)\}\s*\((?P<args>.*)\)")
ARG_RE = re.compile(r"'(?P<key>[^']+)'\s*:\s*(?P<value>'[^']*'|[^,)]*)")
SCRIPT_NAME_RE = r"[A-Za-z0-9_]+"


def parse_socks5_proxy(proxy_url: str) -> Optional[Tuple]:
    if not proxy_url:
        return None

    parsed = urlparse(proxy_url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"socks5", "socks5h"}:
        raise ValueError("Only socks5/socks5h proxies are supported")
    if not parsed.hostname or not parsed.port:
        raise ValueError("Proxy must contain host and port")

    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    rdns = scheme == "socks5h"
    return ("socks5", parsed.hostname, parsed.port, rdns, username, password)


try:
    TELEGRAM_PROXY = parse_socks5_proxy(TG_PROXY)
except ValueError as exc:
    raise RuntimeError(f"Invalid TG_PROXY value: {TG_PROXY!r}. {exc}") from exc

if SESSION_NAME.endswith(".session"):
    SESSION_NAME = SESSION_NAME[: -len(".session")]

if SESSION_STRING:
    log.info("Auth mode: SESSION_STRING")
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH, proxy=TELEGRAM_PROXY)
else:
    session_path = f"{SESSION_NAME}.session"
    log.info("Auth mode: file session (%s)", session_path)
    log.info("Session file exists: %s", os.path.exists(session_path))
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH, proxy=TELEGRAM_PROXY)


def parse_directive_line(raw_line: str) -> Optional[Tuple[str, Dict[str, str]]]:
    line = raw_line.strip()
    if line.startswith("[stdout] "):
        line = line[len("[stdout] ") :]
    if line.startswith("[stderr] "):
        return None

    match = DIRECTIVE_RE.search(line)
    if not match:
        return None

    action = match.group("action")
    args_blob = match.group("args")
    args: Dict[str, str] = {}

    for part in ARG_RE.finditer(args_blob):
        key = part.group("key").strip()
        value = part.group("value").strip()
        if value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1]
        args[key] = value

    return action, args


async def wait_for_value_message(
    chat_id: int, sender_id: int, after_message_id: int, prompt_id: int
):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def on_message(new_event):
        msg = new_event.message
        if msg.id <= after_message_id:
            return
        if not msg.raw_text:
            return
        reply_to_msg_id = getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None)
        if reply_to_msg_id != prompt_id:
            return
        if not future.done():
            future.set_result(msg)

    event_filter = events.NewMessage(chats=chat_id, from_users=sender_id)
    client.add_event_handler(on_message, event_filter)
    try:
        return await asyncio.wait_for(future, timeout=INPUT_TIMEOUT_SECONDS)
    finally:
        client.remove_event_handler(on_message, event_filter)


async def resolve_chat_entity(default_chat_id: int, chat_arg: Optional[str]):
    if not chat_arg:
        return default_chat_id
    raw = chat_arg.strip()
    if raw in {"me", "self"}:
        return "me"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return await client.get_input_entity(raw)


def parse_ids(raw_ids: str) -> List[int]:
    return [int(part.strip()) for part in raw_ids.split(",") if part.strip()]


async def extract_code_from_reply(reply) -> Optional[str]:
    text = (reply.raw_text or "").strip()
    if text:
        return text

    if not reply.document:
        return None

    filename = (getattr(reply.file, "name", None) or "").lower()
    if not filename.endswith(".c"):
        return None

    data = await reply.download_media(file=bytes)
    if not data:
        return None

    if isinstance(data, str):
        with open(data, "rb") as f:
            data = f.read()

    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace").strip()

    return None


async def post_add_script(name: str, content: str) -> Tuple[bool, str]:
    url = f"{BACKEND_HTTP_BASE}/addScript"
    payload = {"name": name, "content": content}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=120) as resp:
                body = await resp.text()
                if resp.status != 200:
                    return False, f"HTTP {resp.status}: {body}"
                data = await resp.json()
                if not data.get("success", False):
                    return False, data.get("message", "unknown error")
                return True, data.get("message", "ok")
    except Exception as exc:
        return False, str(exc)


async def get_scripts() -> Tuple[bool, str]:
    url = f"{BACKEND_HTTP_BASE}/listScripts"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                body = await resp.text()
                if resp.status != 200:
                    return False, f"HTTP {resp.status}: {body}"
                data = await resp.json()
                if not isinstance(data, list):
                    return False, f"unexpected response: {data}"
                if not data:
                    return True, "Скриптов пока нет."
                return True, "Доступные скрипты:\n" + "\n".join(f"- {name}" for name in data)
    except Exception as exc:
        return False, str(exc)


async def run_script_flow(event, script_name: str, target_message_id: int):
    ws_url = f"{BACKEND_WS_BASE}/runScript/{quote(script_name)}/ws"
    chat_id = event.chat_id
    sender_id = event.sender_id
    assert chat_id is not None
    assert sender_id is not None

    last_input_value: Optional[str] = None

    async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
        while True:
            try:
                incoming = await ws.recv()
            except ConnectionClosed:
                break

            if isinstance(incoming, bytes):
                incoming = incoming.decode("utf-8", errors="replace")

            parsed = parse_directive_line(incoming)
            if not parsed:
                continue

            action, args = parsed
            log.info("Directive received: action=%s args=%s", action, args)
            if action == "get_value":
                value_name = args.get("name", "value")
                prompt = await client.send_message(
                    chat_id, f"Введите значение для `{value_name}` (ответом на это сообщение):"
                )
                try:
                    user_msg = await wait_for_value_message(chat_id, sender_id, prompt.id, prompt.id)
                except asyncio.TimeoutError:
                    await client.send_message(chat_id, "Таймаут ожидания ввода. Скрипт остановлен.")
                    break

                value = user_msg.raw_text.strip()
                last_input_value = value
                await user_msg.delete()
                try:
                    await prompt.delete()
                except Exception:
                    pass
                await ws.send(value)

            if action == "get_messages":
                chat_arg = args.get("chat")
                ids_arg = args.get("ids", "")
                limit = int(args.get("limit", "20"))
                entity = await resolve_chat_entity(chat_id, chat_arg)

                if ids_arg:
                    ids = parse_ids(ids_arg)
                    fetched = await client.get_messages(entity, ids=ids)
                    if not isinstance(fetched, list):
                        fetched = [fetched]
                else:
                    fetched = await client.get_messages(entity, limit=limit)

                payload = []
                for msg in fetched:
                    if not msg:
                        continue
                    payload.append(
                        {
                            "id": msg.id,
                            "chat_id": msg.chat_id,
                            "sender_id": msg.sender_id,
                            "date": msg.date.isoformat() if msg.date else None,
                            "text": msg.raw_text or "",
                        }
                    )
                await ws.send(json.dumps(payload, ensure_ascii=False))

            if action == "send_message":
                chat_arg = args.get("chat")
                text = args.get("text", "")
                if text:
                    entity = await resolve_chat_entity(chat_id, chat_arg)
                    sent = await client.send_message(entity, text)
                    await ws.send(str(sent.id))

            if action == "delete_messages":
                chat_arg = args.get("chat")
                ids_arg = args.get("ids", "")
                if ids_arg:
                    ids = parse_ids(ids_arg)
                    entity = await resolve_chat_entity(chat_id, chat_arg)
                    await client.delete_messages(entity, ids, revoke=True)

            if action == "edit_message":
                chat_arg = args.get("chat")
                raw_msg_id = args.get("id", "myid")
                raw_text = args.get("text", "") or (last_input_value or "")
                if not raw_text:
                    await event.reply(
                        "Получена команда edit_message без текста. "
                        "Добавь в C-скрипте параметр `'text':'...'`."
                    )
                    continue

                if raw_msg_id == "myid":
                    msg_id_to_edit = target_message_id
                else:
                    try:
                        msg_id_to_edit = int(raw_msg_id)
                    except ValueError:
                        msg_id_to_edit = target_message_id

                try:
                    entity = await resolve_chat_entity(chat_id, chat_arg)
                    await client.edit_message(entity, msg_id_to_edit, raw_text)
                except Exception as exc:
                    log.exception("Failed to edit message id=%s", msg_id_to_edit)
                    await event.reply(
                        f"Не удалось отредактировать message_id={msg_id_to_edit}: {exc}"
                    )


@client.on(
    events.NewMessage(
        pattern=rf"^{re.escape(COMMAND_PREFIX)}add(?:\s+({SCRIPT_NAME_RE}))?(?:\n|$)", outgoing=True
    )
)
async def add_script_handler(event):
    script_name = event.pattern_match.group(1)
    if not script_name:
        await event.reply(
            f"Использование: {COMMAND_PREFIX}add <name> + код в reply или со следующей строки"
        )
        return

    code: Optional[str] = None
    if event.is_reply:
        reply = await event.get_reply_message()
        code = await extract_code_from_reply(reply)
    else:
        parts = event.raw_text.split("\n", 1)
        if len(parts) == 2:
            code = parts[1].strip()

    if not code:
        await event.reply(
            "Не найден C-код. Отправьте команду в reply на сообщение с кодом "
            "или на файл `*.c`."
        )
        return

    ok, text = await post_add_script(script_name, code)
    if ok:
        await event.reply(f"Скрипт `{script_name}` добавлен: {text}")
    else:
        await event.reply(f"Ошибка добавления `{script_name}`: {text}")


@client.on(events.NewMessage(pattern=rf"^{re.escape(COMMAND_PREFIX)}list$", outgoing=True))
async def list_scripts_handler(event):
    ok, text = await get_scripts()
    await event.reply(text if ok else f"Ошибка: {text}")


@client.on(
    events.NewMessage(
        pattern=rf"^{re.escape(COMMAND_PREFIX)}run\s+({SCRIPT_NAME_RE})(?:\s+(\d+))?$", outgoing=True
    )
)
async def run_script_handler(event):
    script_name = event.pattern_match.group(1)
    explicit_message_id = event.pattern_match.group(2)
    if explicit_message_id:
        target_message_id = int(explicit_message_id)
        try:
            await event.delete()
        except Exception:
            log.exception("Failed to delete run command message")
    else:
        target_message_id = event.message.id

    try:
        await run_script_flow(event, script_name, target_message_id)
    except Exception as exc:
        log.exception("run_script_handler failed")
        await event.reply(f"Ошибка выполнения скрипта: {exc}")


@client.on(events.NewMessage(pattern=rf"^{re.escape(COMMAND_PREFIX)}help$", outgoing=True))
async def help_scripts_handler(event):
    await event.reply(
        "\n".join(
            [
                "Команды:",
                f"{COMMAND_PREFIX}add_script <name>  (в reply на C-код или код со следующей строки)",
                f"{COMMAND_PREFIX}list_scripts",
                f"{COMMAND_PREFIX}run_script <name> [message_id]",
                f"{COMMAND_PREFIX}help_scripts",
                "",
                "Сценарий run_script:",
                "0) если message_id не задан, редактируется сообщение с командой;",
                "   если message_id задан, сообщение с командой удаляется;",
                "1) backend просит {get_value};",
                "2) вы отправляете значение отдельным сообщением;",
                "3) это сообщение удаляется;",
                "4) по {edit_message} редактируется указанное сообщение (или <message_id> при id='myid').",
                "",
                "Доп. действия из скрипта:",
                "{get_messages} ('chat':'me|@user|-100..', 'limit':20) -> JSON в stdin",
                "{get_messages} ('ids':'1,2,3') -> JSON по конкретным id",
                "{send_message} ('chat':'me', 'text':'hello')",
                "{delete_messages} ('chat':'me', 'ids':'1,2,3')",
                "{edit_message} ('chat':'me', 'id':'123', 'text':'new text')",
            ]
        )
    )


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        log.error(
            "Session is not authorized. Run one-time login: "
            "`python -u /app/init_session.py` or `python -u /app/init_session_qr.py`"
        )
        await client.disconnect()
        return

    me = await client.get_me()
    log.info("Userbot started as @%s (%s)", me.username, me.id)
    try:
        await client.send_message("me", "Userbot started successfully.")
        log.info("Startup message sent to Saved Messages")
    except Exception:
        log.exception("Failed to send startup message to Saved Messages")
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
