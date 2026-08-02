from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DecodedMessage:
    protocol: str
    direction: str
    pdu_type: str
    procedure_code: Optional[int]
    procedure_name: str
    message_name: str
    fields: dict[str, Any] = field(default_factory=dict)
    decode_error: Optional[str] = None
