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


def test_logbook_panel_helpers_filter_sort_and_hide_locations():
    values = _node_eval(
        """
        import {
          directoryMeta,
          visibleLocations,
          visiblePeople
        } from './static/js/logbook/panels.js';

        const people = [
          { id: '2', display_name: 'Alex', mention_count: 3, last_mentioned: '2026-06-01', facts: [{ label: 'Role', value_text: 'Coach' }] },
          { id: '1', display_name: 'Jeanine', mention_count: 1, last_mentioned: '2026-06-08', aliases: ['J'] }
        ];
        const locations = [
          { id: 'gym', display_name: 'Gym', mention_count: 2, last_mentioned: '2026-06-05', aliases: ['Training Place'] },
          { id: 'old', display_name: 'Old Office', mention_count: 9, last_mentioned: '2026-05-01', aliases: ['Archive'], hidden: true }
        ];

        console.log(JSON.stringify({
          meta: directoryMeta(people[0], 'Coach'),
          peopleRecent: visiblePeople(people, { sort: 'recent' }).map(item => item.id),
          peopleSearchFact: visiblePeople(people, { search: 'coach' }).map(item => item.id),
          locationsAlias: visibleLocations(locations, { search: 'train' }).map(item => item.id),
          locationsHiddenDefault: visibleLocations(locations, { search: 'archive' }).map(item => item.id),
          locationsHiddenIncluded: visibleLocations(locations, { search: 'archive', includeHidden: true }).map(item => item.id)
        }));
        """
    )

    assert values == {
        "meta": "3 entries | last 2026-06-01 | Coach",
        "peopleRecent": ["1", "2"],
        "peopleSearchFact": ["2"],
        "locationsAlias": ["gym"],
        "locationsHiddenDefault": [],
        "locationsHiddenIncluded": ["old"],
    }


def test_logbook_panel_rendering_keeps_rows_and_suggestions_stable():
    values = _node_eval(
        """
        import {
          renderLocationsPanelHtml,
          renderPeoplePanelHtml
        } from './static/js/logbook/panels.js';

        const escapeHtml = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
        const icon = (kind, size) => `<i data-kind="${kind}" data-size="${size}"></i>`;
        const peopleHtml = renderPeoplePanelHtml({
          entry: { people: [{ display_name: 'Jeanine' }] },
          aiPreview: { people_suggestions: [{ display_name: 'Alex', reason: 'mentioned' }] },
          people: [{ id: 'jeanine', display_name: 'Jeanine', mention_count: 1, last_mentioned: '2026-06-08' }],
          activePersonId: 'jeanine',
          escapeHtml,
          icon,
          personSuggestionMeta: person => person.reason,
          personSuggestionActionLabel: () => 'Link',
          renderFactsPreview: () => '<facts></facts>',
          renderConnectionsPreview: () => '<connections></connections>'
        });
        const locationsHtml = renderLocationsPanelHtml({
          entry: { locations: [{ display_name: 'Gym' }] },
          aiPreview: { location_suggestions: [{ display_name: 'Office', reason: 'visited' }] },
          locations: [
            { id: 'gym', display_name: 'Gym', mention_count: 1, last_mentioned: '2026-06-08' },
            { id: 'old', display_name: 'Old Office', mention_count: 1, hidden: true }
          ],
          activeLocationId: 'gym',
          escapeHtml,
          icon
        });

        console.log(JSON.stringify({
          peopleHasToday: peopleHtml.includes('Jeanine'),
          peopleHasSuggestionAction: peopleHtml.includes('data-add-ai-person="0">Link</button>'),
          peopleHasActiveRow: peopleHtml.includes('logbook-directory-row active'),
          peopleHasInjectedPreviews: peopleHtml.includes('<facts></facts>') && peopleHtml.includes('<connections></connections>'),
          locationHasSuggestion: locationsHtml.includes('data-add-ai-location="0">Add</button>'),
          locationHasActiveRow: locationsHtml.includes('logbook-directory-row active'),
          locationHidesHidden: !locationsHtml.includes('Old Office')
        }));
        """
    )

    assert values == {
        "peopleHasToday": True,
        "peopleHasSuggestionAction": True,
        "peopleHasActiveRow": True,
        "peopleHasInjectedPreviews": True,
        "locationHasSuggestion": True,
        "locationHasActiveRow": True,
        "locationHidesHidden": True,
    }


def test_logbook_panel_event_helpers_bind_rows_and_controls():
    values = _node_eval(
        """
        import {
          bindDirectoryControls,
          bindDirectoryRowActions
        } from './static/js/logbook/panels.js';

        const calls = [];
        const elements = {
          insertPerson: { dataset: { insertPerson: 'Jeanine' }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } },
          filterPerson: { dataset: { filterPerson: 'p1' }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } },
          insertLocation: { dataset: { insertLocation: 'Gym' }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } },
          filterLocation: { dataset: { filterLocation: 'l1' }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } },
          search: { value: 'je', listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } },
          sort: { listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } },
          list: { innerHTML: '' },
          create: { listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } }
        };
        const root = {
          querySelectorAll(selector) {
            return ({
              '[data-insert-person]': [elements.insertPerson],
              '[data-filter-person]': [elements.filterPerson],
              '[data-insert-location]': [elements.insertLocation],
              '[data-filter-location]': [elements.filterLocation]
            })[selector] || [];
          }
        };
        bindDirectoryRowActions(root, {
          onInsertPerson: value => calls.push(['insertPerson', value]),
          onFilterPerson: value => calls.push(['filterPerson', value]),
          onInsertLocation: value => calls.push(['insertLocation', value]),
          onFilterLocation: value => calls.push(['filterLocation', value])
        });
        elements.insertPerson.listeners.click();
        elements.filterPerson.listeners.click();
        elements.insertLocation.listeners.click();
        elements.filterLocation.listeners.click();

        const documentRef = {
          getElementById(id) {
            return ({
              search: elements.search,
              sort: elements.sort,
              list: elements.list,
              create: elements.create
            })[id] || null;
          }
        };
        bindDirectoryControls({
          documentRef,
          searchId: 'search',
          sortId: 'sort',
          listId: 'list',
          createId: 'create',
          onSearch: value => calls.push(['search', value]),
          onSort: value => calls.push(['sort', value]),
          renderRows: () => '<row></row>',
          bindRows: () => calls.push(['bindRows']),
          onCreate: () => calls.push(['create'])
        });
        elements.search.listeners.input();
        elements.sort.listeners.change({ target: { value: 'name' } });
        elements.create.listeners.click();

        console.log(JSON.stringify({ calls, list: elements.list.innerHTML }));
        """
    )

    assert values == {
        "calls": [
            ["insertPerson", "Jeanine"],
            ["filterPerson", "p1"],
            ["insertLocation", "Gym"],
            ["filterLocation", "l1"],
            ["search", "je"],
            ["bindRows"],
            ["sort", "name"],
            ["bindRows"],
            ["create"],
        ],
        "list": "<row></row>",
    }
