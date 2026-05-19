from scraper.decryptors.base import BaseDecryptor


class AESDecoder(BaseDecryptor):
    name = "aes"
    priority = 20

    async def can_handle(self, content: bytes, context: dict) -> bool:
        return bool(context.get("aes_key"))

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad

        key = bytes.fromhex(context["aes_key"])
        mode = context.get("aes_mode", "cbc").upper()
        iv = bytes.fromhex(context.get("aes_iv", "00" * 16))

        if mode == "ECB":
            cipher = AES.new(key, AES.MODE_ECB)
        elif mode == "GCM":
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv[:16])
            return cipher.decrypt_and_verify(content[:-16], content[-16:])
        else:
            cipher = AES.new(key, AES.MODE_CBC, iv)

        try:
            return unpad(cipher.decrypt(content), 16)
        except Exception:
            return cipher.decrypt(content)
