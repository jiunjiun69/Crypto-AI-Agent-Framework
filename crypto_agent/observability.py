from __future__ import annotations

import json
from typing import Any, Dict, Optional

from config import (
    LANGFUSE_ENABLED,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LANGFUSE_HOST,
)

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover
    Langfuse = None


def safe_preview(x: Any, n: int = 1200) -> str:
    try:
        if isinstance(x, str):
            s = x
        else:
            s = json.dumps(x, ensure_ascii=False, default=str)
    except Exception:
        s = str(x)
    return s[:n]


_langfuse: Optional["Langfuse"] = None


def get_langfuse_client() -> Optional["Langfuse"]:
    global _langfuse
    if _langfuse is not None:
        return _langfuse

    if (
        (not LANGFUSE_ENABLED)
        or Langfuse is None
        or not LANGFUSE_PUBLIC_KEY
        or not LANGFUSE_SECRET_KEY
        or not LANGFUSE_HOST
    ):
        _langfuse = None
        return None

    try:
        _langfuse = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        print("[INFO] Langfuse enabled:", LANGFUSE_HOST)
    except Exception as e:
        print("[WARN] Langfuse init failed:", repr(e))
        _langfuse = None

    return _langfuse


class ObsCtx:
    def __init__(self, as_type: str, name: str, input_: Dict[str, Any] | None = None, metadata: Dict[str, Any] | None = None):
        self.as_type = as_type
        self.name = name
        self.input_ = input_ or {}
        self.metadata = metadata or {}
        self._cm = None
        self.obs = None

    def __enter__(self):
        lf = get_langfuse_client()
        if lf is None:
            return self
        try:
            self._cm = lf.start_as_current_observation(
                as_type=self.as_type,
                name=self.name,
                input=self.input_,
                metadata=self.metadata,
            )
            self.obs = self._cm.__enter__()
        except Exception as e:
            print(f"[WARN] Langfuse {self.as_type} create failed:", repr(e))
            self._cm = None
            self.obs = None
        return self

    def update(self, *, output: Dict[str, Any] | None = None, metadata: Dict[str, Any] | None = None):
        if self.obs is None:
            return
        try:
            kwargs = {}
            if output is not None:
                kwargs["output"] = output
            if metadata is not None:
                kwargs["metadata"] = metadata
            if kwargs:
                self.obs.update(**kwargs)
        except Exception as e:
            print(f"[WARN] Langfuse {self.as_type}.update failed:", repr(e))

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.update(metadata={"status": "error", "error": repr(exc)})
        if self._cm is not None:
            return self._cm.__exit__(exc_type, exc, tb)
        return False


class SpanCtx(ObsCtx):
    def __init__(self, name: str, input_: Dict[str, Any] | None = None, metadata: Dict[str, Any] | None = None):
        super().__init__("span", name, input_=input_, metadata=metadata)


class GenCtx(ObsCtx):
    def __init__(self, name: str, input_: Dict[str, Any] | None = None, metadata: Dict[str, Any] | None = None):
        super().__init__("generation", name, input_=input_, metadata=metadata)