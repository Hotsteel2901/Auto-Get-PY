import ast
from scraper.decryptors.base import BaseDecryptor


class CustomExprDecoder(BaseDecryptor):
    name = "custom"
    priority = 100

    async def can_handle(self, content: bytes, context: dict) -> bool:
        return bool(context.get("custom_expr"))

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        expr = context["custom_expr"]
        try:
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    raise ValueError("Imports not allowed in custom expressions")
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id not in ("bytes", "int", "len", "range"):
                        if hasattr(node.func, 'id'):
                            allowed = {"bytes", "int", "len", "range", "list", "bytearray"}
                            if node.func.id not in allowed:
                                raise ValueError(f"Function call not allowed: {node.func.id}")
            local_vars = {"content": content, "bytes": bytes, "int": int, "len": len, "range": range, "list": list, "bytearray": bytearray}
            result = eval(compile(tree, "<custom_expr>", "eval"), {"__builtins__": {}}, local_vars)
        except (SyntaxError, ValueError):
            raise
        if isinstance(result, str):
            return result.encode("utf-8")
        return bytes(result)
