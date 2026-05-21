"""Integration flow test: Data -> Factor -> Signal.

Plan v10 Phase P Proposal 5: scaffold pending implementation (Phase J defer).
Covers daily production chain: Tushare data ingest -> factor compute -> signal generation.

铁律 9 (并发限制): runs in solo mode (no parallel DB calls).
Phase B-1 frozen: pytest.mark.skip prevents accidental DB mutation.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Plan v10 Phase P scaffold -- Phase J implementation defer")
def test_synthetic_tushare_data_to_factor_to_signal():
    """End-to-end: inject synthetic Tushare bars -> factor_values update -> signal_service target list."""
    pass


@pytest.mark.skip(reason="Plan v10 Phase P scaffold -- Phase J implementation defer")
def test_data_pipeline_iron_law_17_no_raw_insert():
    """Verify DataPipeline.ingest is the only path for factor_values writes (铁律 17)."""
    pass
