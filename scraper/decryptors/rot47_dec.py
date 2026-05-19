from scraper.decryptors.base import BaseDecryptor


class Rot47Decoder(BaseDecryptor):
    name = "rot47"
    priority = 50

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore")
            printable = sum(1 for c in text if 33 <= ord(c) <= 126)
            return printable / max(len(text), 1) > 0.8
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        result = []
        for b in content:
            if 33 <= b <= 126:
                result.append(33 + ((b - 33 + 47) % 94))
            else:
                result.append(b)
        return bytes(result)
