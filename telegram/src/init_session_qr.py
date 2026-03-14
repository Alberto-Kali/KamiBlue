import asyncio
import os
from urllib.parse import unquote, urlparse

import telethon
from qrcode import QRCode
from telethon import TelegramClient
from telethon.sessions import StringSession


API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
TG_SESSION = os.getenv("TG_SESSION", "/data/userbot")
QR_WAIT_SECONDS = int(os.getenv("QR_WAIT_SECONDS", "30"))
TG_PROXY = os.getenv("TG_PROXY", "").strip()


def print_qr(data: str) -> None:
    qr = QRCode()
    qr.add_data(data)
    qr.print_ascii(invert=True)


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


async def main() -> None:
    proxy = parse_socks5_proxy(TG_PROXY)
    client = TelegramClient(TG_SESSION, API_ID, API_HASH, proxy=proxy)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already authorized as: id={me.id} username={me.username}")
    else:
        qr_login = await client.qr_login()
        print("Scan this QR with Telegram app (Settings -> Devices -> Link Desktop Device):")
        print_qr(qr_login.url)

        authorized = False
        while not authorized:
            try:
                await qr_login.wait(timeout=QR_WAIT_SECONDS)
                authorized = True
            except telethon.errors.SessionPasswordNeededError:
                password = input("2FA password: ")
                await client.sign_in(password=password)
                authorized = True
            except TimeoutError:
                print("QR expired. Recreating...")
                await qr_login.recreate()
                print_qr(qr_login.url)

        me = await client.get_me()
        print(f"Authorized as: id={me.id} username={me.username}")

    session_string = StringSession.save(client.session)
    print("")
    print("SESSION_STRING (optional):")
    print(session_string)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
