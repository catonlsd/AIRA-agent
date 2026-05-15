from abc import ABC, abstractmethod
from schemas.aira_state import AiraXState


class BaseAgent(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, state: AiraXState) -> AiraXState:
        pass
        