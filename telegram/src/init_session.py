import asyncio
import os
from urllib.parse import unquote, urlparse

from telethon import TelegramClient
from telethon.sessions import StringSession


API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
TG_SESSION = os.getenv("TG_SESSION", "/data/userbot")
TG_PROXY = os.getenv("TG_PROXY", "").strip()


def parse_socks5_proxy(proxy_url: str):
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


async def main():
    proxy = parse_socks5_proxy(TG_PROXY)
    client = TelegramClient(TG_SESSION, API_ID, API_HASH, proxy=proxy)
    await client.start()
    me = await client.get_me()
    session_string = StringSession.save(client.session)

    print(f"Authorized as: id={me.id} username={me.username}")
    print("")
    print("SESSION_STRING (save this if you prefer env-based auth):")
    print(session_string)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
