from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class DecryptorResult:
    success: bool
    data: bytes
    decryptor_name: str = ""


class BaseDecryptor(ABC):
    name: str = "base"
    priority: int = 50

    @abstractmethod
    async def can_handle(self, content: bytes, context: dict) -> bool:
        ...

    @abstractmethod
    async def decrypt(self, content: bytes, context: dict) -> bytes:
        ...


_registry: list[BaseDecryptor] = []


def register(dec: BaseDecryptor):
    _registry.append(dec)


def get_enabled_decryptors(enabled_names: list[str]) -> list[BaseDecryptor]:
    filtered = [d for d in _registry if d.name in enabled_names]
    filtered.sort(key=lambda d: d.priority)
    return filtered


async def run_pipeline(content: bytes, enabled_names: list[str], context: dict,
                      max_passes: int = 3) -> DecryptorResult:
    decryptors = get_enabled_decryptors(enabled_names)
    if not decryptors:
        return DecryptorResult(success=True, data=content)
    current = content
    for _ in range(max_passes):
        handled = False
        for dec in decryptors:
            try:
                if await dec.can_handle(current, context):
                    current = await dec.decrypt(current, context)
                    handled = True
                    break
            except Exception as e:
                logger.warning("Decryptor %s failed: %s", dec.name, e)
                continue
        if not handled:
            break
    return DecryptorResult(success=True, data=current)
