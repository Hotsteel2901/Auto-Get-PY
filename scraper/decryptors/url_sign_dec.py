from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from scraper.decryptors.base import BaseDecryptor


class URLSignDecoder(BaseDecryptor):
    name = "url_sign"
    priority = 40

    SIGN_PARAMS = {"sign", "signature", "token", "expires", "expire", "timestamp", "ts", "nonce", "auth", "auth_key", "access_token"}

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore")
            parsed = urlparse(text)
            return any(p in parsed.query.lower() for p in self.SIGN_PARAMS)
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        text = content.decode("ascii", errors="ignore")
        parsed = urlparse(text)
        params = parse_qs(parsed.query, keep_blank_values=True)
        extra = set(context.get("url_sign_extra_params", "").split(",")) if context.get("url_sign_extra_params") else set()
        strip_params = self.SIGN_PARAMS | {p.strip().lower() for p in extra if p.strip()}

        cleaned = {k: v for k, v in params.items() if k.lower() not in strip_params}
        new_query = urlencode(cleaned, doseq=True)
        new_parsed = parsed._replace(query=new_query)
        return urlunparse(new_parsed).encode("ascii")
