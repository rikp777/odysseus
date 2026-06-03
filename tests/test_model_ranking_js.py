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


def test_model_intelligence_ranking_orders_common_model_tiers():
    values = _node_eval(
        """
        import { modelIntelligenceLabel, modelIntelligenceScore } from './static/js/modelRanking.js';
        const opus = modelIntelligenceScore('anthropic-claude-opus-4');
        const sonnet = modelIntelligenceScore('anthropic-claude-sonnet-4.5');
        const mini = modelIntelligenceScore('openai-gpt-4o-mini');
        const router = modelIntelligenceScore('router:general');
        console.log(JSON.stringify({
          opus,
          sonnet,
          mini,
          router,
          opusLabel: modelIntelligenceLabel(opus),
          routerLabel: modelIntelligenceLabel(router)
        }));
        """
    )

    assert values["opus"] > values["sonnet"] > values["mini"] > values["router"]
    assert values["opusLabel"] == "Top"
    assert values["routerLabel"] == "Utility"
