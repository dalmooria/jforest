# jforest/util.py
from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Summary:
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list = field(default_factory=list)

    def line(self) -> str:
        return f"성공 {self.ok}건 / 건너뜀 {self.skipped}건 / 실패 {self.failed}건"
