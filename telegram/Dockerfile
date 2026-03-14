FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir telethon aiohttp websockets qrcode "python-socks[asyncio]"

COPY telegram/src/main.py /app/main.py
COPY telegram/src/init_session.py /app/init_session.py
COPY telegram/src/init_session_qr.py /app/init_session_qr.py
RUN mkdir -p /data

ENV TG_SESSION=/data/userbot

CMD ["python", "-u", "/app/main.py"]
