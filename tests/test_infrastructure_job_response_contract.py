from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.infrastructure.contracts.infrastructure import validate_value


def test_job_accepted_response_reports_retry_wait_without_state_projection():
    response = {
        "command_id": "12345678-1234-4234-8234-123456789abc",
        "job_id": "87654321-4321-4321-8321-cba987654321",
        "job_type": "INFRA_WORKBOOK_STAGE_V1",
        "state": "retry_wait",
    }
    assert validate_value("INFRA_JOB_ACCEPTED_V1", response) == response
    with pytest.raises(ValidationError):
        validate_value("INFRA_JOB_ACCEPTED_V1", {**response, "state": "unknown"})
