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


def test_logbook_autocomplete_context_detects_people_and_places():
    values = _node_eval(
        """
        import { entityAutocompleteContext } from './static/js/logbook/autocomplete.js';

        console.log(JSON.stringify({
          person: entityAutocompleteContext('Talked to @Je', 13),
          location: entityAutocompleteContext('Went to #Gy', 11),
          middle: entityAutocompleteContext('email@domain', 12),
          rawText: entityAutocompleteContext('Talked to Jeanine', 17)
        }));
        """
    )

    assert values == {
        "person": {"kind": "person", "start": 10, "end": 13, "query": "je"},
        "location": {"kind": "location", "start": 8, "end": 11, "query": "gy"},
        "middle": None,
        "rawText": None,
    }


def test_logbook_autocomplete_matches_names_aliases_and_hides_hidden_locations():
    values = _node_eval(
        """
        import { entityAutocompleteMatches } from './static/js/logbook/autocomplete.js';

        const items = [
          { id: '1', display_name: 'Jeanine Peeters', aliases: ['J'], hidden: false },
          { id: '2', display_name: 'Gym', aliases: ['Training Place'], hidden: false },
          { id: '3', display_name: 'Old Office', aliases: ['Archive'], hidden: true }
        ];

        console.log(JSON.stringify({
          alias: entityAutocompleteMatches(items, 'train').map(item => item.id),
          hiddenDefault: entityAutocompleteMatches(items, 'archive').map(item => item.id),
          hiddenIncluded: entityAutocompleteMatches(items, 'archive', { includeHidden: true }).map(item => item.id),
          limited: entityAutocompleteMatches(items, '', { limit: 2 }).map(item => item.id)
        }));
        """
    )

    assert values == {
        "alias": ["2"],
        "hiddenDefault": [],
        "hiddenIncluded": ["3"],
        "limited": ["1", "2"],
    }
