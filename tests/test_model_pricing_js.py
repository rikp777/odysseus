import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node_eval(source: str):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_model_price_formatter_handles_io_and_unit_prices():
    values = _node_eval(
        """
        import { formatModelPrice, modelPriceSortValue } from './static/js/modelPricing.js';
        const ioPricing = {
          input_usd_per_unit: 0.45,
          output_usd_per_unit: 1.70,
          unit: '1M tokens'
        };
        const unitPricing = {
          price_usd_per_unit: 20,
          unit: '1M character tokens'
        };
        console.log(JSON.stringify({
          io: formatModelPrice(ioPricing),
          unit: formatModelPrice(unitPricing),
          missing: formatModelPrice(null),
          ioSort: modelPriceSortValue(ioPricing),
          unitSort: modelPriceSortValue(unitPricing),
          missingSort: modelPriceSortValue(null)
        }));
        """
    )

    assert values["io"] == {
        "compact": "$0.45/$1.70 · 1M tok",
        "button": "$0.45/$1.70",
        "detail": "Input $0.45 / output $1.70 per 1M tokens",
    }
    assert values["unit"] == {
        "compact": "$20 · 1M chars",
        "button": "$20",
        "detail": "$20 per 1M character tokens",
    }
    assert values["missing"] is None
    assert values["ioSort"] == 1.075
    assert values["unitSort"] == 20
    assert values["missingSort"] is None
