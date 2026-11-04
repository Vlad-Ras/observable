"""Create a private deployment .env once; display the in-game configuration."""
import os
import re
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent
env = root / ".env"
if not env.exists():
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("PUBLIC_URL=https://observable.roften.ru\n")
        f.write("UPLOAD_TOKEN=" + secrets.token_urlsafe(32) + "\n")
        f.write("RETENTION_DAYS=30\n")
values = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line and not line.startswith("#"))
token = values.get("UPLOAD_TOKEN", "")
if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", token):
    raise SystemExit("Invalid UPLOAD_TOKEN in .env")
print('После запуска HTTPS выполните от администратора в Minecraft:')
print('/observable set uploadURL "' + values["PUBLIC_URL"].rstrip("/") + '/v1/add/' + token + '"')
print('Команда содержит секрет загрузки. Не публикуйте её или файл .env.')
