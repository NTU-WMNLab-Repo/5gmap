import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Optional


class PycrateDecoderUnavailable(RuntimeError):
    pass


@dataclass
class PycrateDecodeResult:
    ok: bool
    value: Optional[Any] = None
    fields: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class PycratePerDecoder:
    """Small adapter around pycrate-generated ASN.1 modules."""

    def __init__(self, module_name: Optional[str], object_name: str = "F1AP_PDU") -> None:
        self.module_name = module_name
        self.object_name = object_name
        self._asn_object = None

    @property
    def enabled(self) -> bool:
        return bool(self.module_name)

    def load(self) -> None:
        if not self.module_name:
            raise PycrateDecoderUnavailable("pycrate module is not configured")

        if self._asn_object is not None:
            return

        try:
            module = importlib.import_module(self.module_name)
            candidate = getattr(module, self.object_name)
        except Exception as exc:
            raise PycrateDecoderUnavailable(
                f"could not load {self.module_name}.{self.object_name}: {exc}"
            ) from exc

        self._asn_object = candidate() if isinstance(candidate, type) else candidate

    def decode_aper(self, payload: bytes) -> PycrateDecodeResult:
        if not self.enabled:
            return PycrateDecodeResult(ok=False, error="pycrate module is not configured")

        try:
            self.load()
            asn_object = self._asn_object
            if asn_object is None:
                raise PycrateDecoderUnavailable("pycrate ASN.1 object did not load")

            if hasattr(asn_object, "from_aper"):
                asn_object.from_aper(payload)
            elif hasattr(asn_object, "from_bytes"):
                asn_object.from_bytes(payload)
            else:
                raise PycrateDecoderUnavailable(
                    f"{self.module_name}.{self.object_name} has no from_aper/from_bytes"
                )

            value = asn_object()
            return PycrateDecodeResult(
                ok=True,
                value=value,
                fields={
                    "asn1.value": repr(value)[:1024],
                    "asn1.decoder": "pycrate",
                },
            )
        except Exception as exc:
            logging.debug("pycrate APER decode failed", exc_info=True)
            return PycrateDecodeResult(ok=False, error=str(exc))

