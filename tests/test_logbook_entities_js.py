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


def test_logbook_entity_helpers_resolve_links_and_hide_hidden_places():
    values = _node_eval(
        """
        import {
          currentEntitiesFromContent,
          entityListSignature,
          linkTargetForEntity,
          locationForLink,
          personForLink,
          selectionLinkTarget,
          slugName
        } from './static/js/logbook/entities.js';

        const people = [
          { id: 'person-1', display_name: 'Jeanine Peeters', canonical_name: 'jeanine peeters', aliases: ['Jeanine'] }
        ];
        const locations = [
          { id: 'loc-1', display_name: 'Gym', canonical_name: 'gym', aliases: ['Training Place'], hidden: true },
          { id: 'loc-2', display_name: 'Office', canonical_name: 'office', aliases: [], hidden: false }
        ];
        const parsed = currentEntitiesFromContent(
          'Saw [Jeanine](person:jeanine_peeters) at [Gym](place:gym), then #Office.',
          { people, locations }
        );

        console.log(JSON.stringify({
          slug: slugName('person:J\\u00e9anine Peeters!'),
          personId: personForLink(people, 'person:jeanine_peeters', 'Jeanine')?.id || null,
          hiddenDefault: locationForLink(locations, 'place:gym', 'Gym')?.id || null,
          hiddenIncluded: locationForLink(locations, 'place:gym', 'Gym', { includeHidden: true })?.id || null,
          people: parsed.people.map(item => item.display_name),
          locations: parsed.locations.map(item => item.display_name),
          signature: entityListSignature(parsed.people, parsed.locations),
          personTargetFromEntity: linkTargetForEntity('person', people[0], 'Jeanine'),
          locationTargetFromEntity: linkTargetForEntity('location', locations[1], 'Office'),
          personTarget: selectionLinkTarget('person', 'Jeanine', { people, locations }),
          locationTarget: selectionLinkTarget('location', 'Office', { people, locations }),
          foodTarget: selectionLinkTarget('food', 'Breakfast', { people, locations })
        }));
        """
    )

    assert values == {
        "slug": "jeanine_peeters",
        "personId": "person-1",
        "hiddenDefault": None,
        "hiddenIncluded": "loc-1",
        "people": ["Jeanine Peeters"],
        "locations": ["Office"],
        "signature": "person-1|loc-2",
        "personTargetFromEntity": "person:jeanine_peeters",
        "locationTargetFromEntity": "place:office",
        "personTarget": "person:jeanine_peeters",
        "locationTarget": "place:office",
        "foodTarget": "data:food",
    }


def test_logbook_selection_link_parts_preserve_surrounding_space():
    values = _node_eval(
        """
        import { mentionMarkdown, locationMarkdown, selectionLinkParts } from './static/js/logbook/entities.js';

        console.log(JSON.stringify({
          parts: selectionLinkParts('  [Jeanine]\\nPeeters  '),
          empty: selectionLinkParts('   '),
          mention: mentionMarkdown('Jeanine Peeters', [{ display_name: 'Jeanine Peeters', canonical_name: 'jeanine peeters' }]),
          location: locationMarkdown('Training Place', [{ display_name: 'Gym', canonical_name: 'gym', aliases: ['Training Place'] }])
        }));
        """
    )

    assert values == {
        "parts": {"leading": "  ", "label": "Jeanine Peeters", "trailing": "  "},
        "empty": None,
        "mention": "[Jeanine Peeters](person:jeanine_peeters)",
        "location": "[Training Place](place:gym)",
    }


def test_logbook_entity_resolution_prioritizes_explicit_targets_over_aliases():
    values = _node_eval(
        """
        import { locationForLink, personForLink } from './static/js/logbook/entities.js';

        const people = [
          { id: 'alice', display_name: 'Alice', canonical_name: 'alice', aliases: ['Jan', 'A Team'] },
          { id: 'jan', display_name: 'jan', canonical_name: 'jan', aliases: [] },
          { id: 'test', display_name: 'Test', canonical_name: 'test', aliases: ['Jan'] }
        ];
        const locations = [
          { id: 'cafe', display_name: 'Cafe', canonical_name: 'cafe', aliases: ['Gym'], hidden: false },
          { id: 'gym', display_name: 'Gym', canonical_name: 'gym', aliases: [], hidden: false }
        ];

        console.log(JSON.stringify({
          personTarget: personForLink(people, 'person:jan', 'Alias')?.id || null,
          personLabel: personForLink(people, 'person:unknown', 'Jan')?.id || null,
          personAliasTargetFallback: personForLink(people, 'person:a_team', '')?.id || null,
          locationTarget: locationForLink(locations, 'place:gym', 'Cafe')?.id || null,
          locationLabel: locationForLink(locations, 'place:unknown', 'Gym')?.id || null
        }));
        """
    )

    assert values == {
        "personTarget": "jan",
        "personLabel": "jan",
        "personAliasTargetFallback": "alice",
        "locationTarget": "gym",
        "locationLabel": "gym",
    }


def test_logbook_entities_drop_after_unlinking_markdown():
    values = _node_eval(
        """
        import { currentEntitiesFromContent } from './static/js/logbook/entities.js';
        import { unlinkMarkdownSelection } from './static/js/logbook/editor.js';

        const people = [{ id: 'person-1', display_name: 'Jeanine', canonical_name: 'jeanine', aliases: [] }];
        const locations = [{ id: 'loc-1', display_name: 'Gym', canonical_name: 'gym', aliases: [], hidden: false }];
        const content = '[Jeanine](person:jeanine) visited [Gym](place:gym)';
        const unlinked = unlinkMarkdownSelection(content, 0, content.length);
        const parsed = currentEntitiesFromContent(unlinked.text, { people, locations });

        console.log(JSON.stringify({
          text: unlinked.text,
          people: parsed.people.length,
          locations: parsed.locations.length
        }));
        """
    )

    assert values == {
        "text": "Jeanine visited Gym",
        "people": 0,
        "locations": 0,
    }
