from scraper.decryptors.base import (
    BaseDecryptor,
    DecryptorResult,
    register,
    get_enabled_decryptors,
    run_pipeline,
)
from scraper.decryptors.base64_dec import Base64Decoder
from scraper.decryptors.hex_dec import HexDecoder
from scraper.decryptors.rot47_dec import Rot47Decoder
from scraper.decryptors.aes_dec import AESDecoder
from scraper.decryptors.xor_dec import XORDecoder
from scraper.decryptors.url_sign_dec import URLSignDecoder
from scraper.decryptors.custom_dec import CustomExprDecoder


def register_all():
    from scraper.decryptors.base import _registry
    if _registry:
        return
    register(Base64Decoder())
    register(HexDecoder())
    register(Rot47Decoder())
    register(AESDecoder())
    register(XORDecoder())
    register(URLSignDecoder())
    register(CustomExprDecoder())


__all__ = [
    "BaseDecryptor",
    "DecryptorResult",
    "register",
    "get_enabled_decryptors",
    "run_pipeline",
    "register_all",
    "Base64Decoder",
    "HexDecoder",
    "Rot47Decoder",
    "AESDecoder",
    "XORDecoder",
    "URLSignDecoder",
    "CustomExprDecoder",
]
