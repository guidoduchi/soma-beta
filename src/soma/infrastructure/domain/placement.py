from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError, ValidationError


def validate_rack_height(height_u: int) -> int:
    if type(height_u) is not int or not 1 <= height_u <= 120:
        raise ValidationError("Rack height must be an integer between 1 and 120 U")
    return height_u


@dataclass(frozen=True, slots=True)
class RackInterval:
    """Validated half-open U interval; adjacency does not imply overlap."""

    u_start: int
    u_span: int

    def __post_init__(self) -> None:
        if (
            type(self.u_start) is not int
            or type(self.u_span) is not int
            or self.u_start < 1
            or self.u_span < 1
        ):
            raise SomaError("RACK_U_OUT_OF_RANGE", "U start and span must be positive integers")

    @property
    def end_exclusive(self) -> int:
        return self.u_start + self.u_span

    def require_fits(self, height_u: int) -> None:
        validate_rack_height(height_u)
        if self.end_exclusive - 1 > height_u:
            raise SomaError("RACK_U_OUT_OF_RANGE", "Placement exceeds Rack height")

    def overlaps(self, other: RackInterval) -> bool:
        return self.u_start < other.end_exclusive and other.u_start < self.end_exclusive


def validate_rack_placement(
    *,
    network_element_site_id: str,
    rack_site_id: str,
    height_u: int,
    u_start: int,
    u_span: int,
) -> RackInterval:
    """Validate geometry/site; the writer must separately query current occupancy."""
    if network_element_site_id != rack_site_id:
        raise SomaError("PLACEMENT_CROSS_SITE", "Rack and Network Element Sites differ")
    interval = RackInterval(u_start, u_span)
    interval.require_fits(height_u)
    return interval
