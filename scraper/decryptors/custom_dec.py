from scraper.decryptors.base import BaseDecryptor


class CustomExprDecoder(BaseDecryptor):
    name = "custom"
    priority = 100

    async def can_handle(self, content: bytes, context: dict) -> bool:
        return bool(context.get("custom_expr"))

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        expr = context["custom_expr"]
        local_vars = {"content": content, "bytes": bytes}
        result = eval(expr, {"__builtins__": {}}, local_vars)
        if isinstance(result, str):
            return result.encode("utf-8")
        return bytes(result)
