from sqlalchemy.orm import Session

from app.memory.service import MemoryService


class MemoryAgent:
    def __init__(self) -> None:
        self.service = MemoryService()

    def context(self, db: Session) -> tuple[list[dict], dict]:
        return self.service.recent_history(db), self.service.preferences(db)

    def store_turn(self, db: Session, question: str, answer: str, citations: list[dict]) -> None:
        self.service.add_message(db, "user", question)
        self.service.add_message(db, "assistant", answer, citations)

    def clear(self, db: Session) -> None:
        self.service.clear_history(db)
