from abc import ABC, abstractmethod
from pathlib import Path


class Engine(ABC):
    name: str

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def edges(self) -> list[tuple[str, str]]:
        """Format pairs (from, to) this engine can convert directly."""

    @abstractmethod
    def convert(
        self, src: Path, dst: Path, src_fmt: str, dst_fmt: str
    ) -> None: ...
