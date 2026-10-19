from .base import VoiceEngine
from .fake import FakeEngine

ENGINES: dict[str, type[VoiceEngine]] = {"fake": FakeEngine}


def get_engine(name: str) -> VoiceEngine:
    try:
        return ENGINES[name]()
    except KeyError:
        raise ValueError(f"unknown engine {name!r}") from None
