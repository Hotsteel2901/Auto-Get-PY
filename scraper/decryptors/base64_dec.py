import base64
import re
from scraper.decryptors.base import BaseDecryptor


class Base64Decoder(BaseDecryptor):
    name = "base64"
    priority = 10

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore").strip()
            return bool(re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", text)) and len(text) >= 16
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        text = content.decode("ascii", errors="ignore").strip()
        padding = 4 - len(text) % 4
        if padding != 4:
            text += "=" * padding
        return base64.b64decode(text)
