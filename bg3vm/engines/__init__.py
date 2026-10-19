from .base import VoiceEngine
from .fake import FakeEngine
from .rvc_applio import RvcApplioEngine

ENGINES: dict[str, type[VoiceEngine]] = {"rvc": RvcApplioEngine, "fake": FakeEngine}
DEFAULT_ENGINE = "rvc"


def get_engine(name: str) -> VoiceEngine:
    try:
        return ENGINES[name]()
    except KeyError:
        raise ValueError(f"unknown engine {name!r}") from None
