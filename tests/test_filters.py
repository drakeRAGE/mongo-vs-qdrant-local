from __future__ import annotations

import pytest

from src.config import CATEGORIES, TENANTS
from src.runners.study import _filters_for


def test_unfiltered():
    filt, name = _filters_for("100")
    assert filt is None
    assert name == "unfiltered"


def test_fifty_percent_is_year_cutoff():
    filt, name = _filters_for("50")
    assert filt == {"year_gte": 2022}
    assert name == "year>=2022"


def test_ten_percent_is_one_tenant():
    filt, name = _filters_for("10")
    assert filt == {"tenant_id": TENANTS[0]}
    assert TENANTS[0] == "t00"
    assert "t00" in name


def test_one_percent_is_tenant_and_category():
    filt, name = _filters_for("1")
    assert filt == {"tenant_id": TENANTS[0], "category": CATEGORIES[0]}
    assert CATEGORIES[0] == "health"


def test_unknown_selectivity_raises():
    with pytest.raises(ValueError):
        _filters_for("33")
