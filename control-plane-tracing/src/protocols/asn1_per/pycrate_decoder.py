import importlib
import logging
import os
from copy import deepcopy
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

    def __init__(
        self,
        module_name: Optional[str],
        object_name: str = "F1AP_PDU",
        *,
        repr_limit: Optional[int] = None,
    ) -> None:
        self.module_name = module_name
        self.object_name = object_name
        self._asn_object = None
        self._load_error: Optional[str] = None
        self.repr_limit = repr_limit or int(os.getenv("ASN1_VALUE_REPR_LIMIT", "2048"))

    @property
    def enabled(self) -> bool:
        return bool(self.module_name)

    def load(self) -> None:
        if not self.module_name:
            raise PycrateDecoderUnavailable("pycrate module is not configured")

        if self._load_error:
            raise PycrateDecoderUnavailable(self._load_error)

        if self._asn_object is not None:
            return

        try:
            module = importlib.import_module(self.module_name)
            candidate = module
            for name in self.object_name.split("."):
                candidate = getattr(candidate, name)
        except Exception as exc:
            self._load_error = f"could not load {self.module_name}.{self.object_name}: {exc}"
            raise PycrateDecoderUnavailable(self._load_error) from exc

        self._asn_object = candidate() if isinstance(candidate, type) else candidate

    def decode_aper(self, payload: bytes) -> PycrateDecodeResult:
        if not self.enabled:
            return PycrateDecodeResult(ok=False, error="pycrate module is not configured")

        try:
            self.load()
            asn_object = self._asn_object
            if asn_object is None:
                raise PycrateDecoderUnavailable("pycrate ASN.1 object did not load")

            # pycrate generated modules usually expose singleton ASN.1 objects.
            # Decode into a copy so later decodes do not reuse mutated state.
            try:
                asn_object = deepcopy(asn_object)
            except Exception:
                logging.debug("could not deepcopy pycrate ASN.1 object", exc_info=True)

            if hasattr(asn_object, "from_aper"):
                asn_object.from_aper(payload)
            elif hasattr(asn_object, "from_bytes"):
                asn_object.from_bytes(payload)
            else:
                raise PycrateDecoderUnavailable(
                    f"{self.module_name}.{self.object_name} has no from_aper/from_bytes"
                )

            if hasattr(asn_object, "get_val"):
                value = asn_object.get_val()
            else:
                value = asn_object()

            show = None
            if os.getenv("ASN1_INCLUDE_SHOW", "0") == "1" and hasattr(asn_object, "show"):
                show = asn_object.show()

            fields = {
                "asn1.decoder": "pycrate",
                "asn1.module": self.module_name,
                "asn1.object": self.object_name,
                "asn1.value": repr(value)[: self.repr_limit],
            }
            if show is not None:
                fields["asn1.show"] = show[: self.repr_limit]

            return PycrateDecodeResult(
                ok=True,
                value=value,
                fields=fields,
            )
        except Exception as exc:
            logging.debug("pycrate APER decode failed", exc_info=True)
            return PycrateDecodeResult(ok=False, error=str(exc))
