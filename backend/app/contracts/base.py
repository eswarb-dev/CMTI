from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base class for shared API contracts.

    Extra fields are forbidden so future modules cannot silently extend
    frozen STEP 04 schemas outside the explicit metadata extension fields.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

