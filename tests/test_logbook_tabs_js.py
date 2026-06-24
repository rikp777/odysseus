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


def test_logbook_tab_transition_closes_write_only_overlays():
    values = _node_eval(
        """
        import {
          LOGBOOK_TABS,
          logbookTabLabel,
          logbookTabTransition,
          normalizeLogbookTab
        } from './static/js/logbook/tabs.js';

        const openWriteState = {
          browseOpen: true,
          writeToolsOpen: true,
          historyOpen: true
        };

        console.log(JSON.stringify({
          tabs: LOGBOOK_TABS,
          aiLabel: logbookTabLabel('ai'),
          mood: logbookTabTransition('mood', openWriteState),
          data: logbookTabTransition('data', openWriteState),
          review: logbookTabTransition('review', openWriteState),
          people: logbookTabTransition('people', openWriteState),
          places: logbookTabTransition('places', openWriteState),
          enhance: logbookTabTransition('ai', openWriteState),
          writeKeepsState: logbookTabTransition('write', openWriteState),
          unknown: normalizeLogbookTab('broken')
        }));
        """
    )

    expected_closed = {
        "action": "tab",
        "browseOpen": False,
        "writeToolsOpen": False,
        "historyOpen": False,
    }
    assert values["tabs"] == ["write", "mood", "data", "review", "people", "places", "ai"]
    assert values["aiLabel"] == "Enhance"
    assert values["mood"] == {**expected_closed, "activeTab": "mood"}
    assert values["data"] == {**expected_closed, "activeTab": "data"}
    assert values["review"] == {**expected_closed, "activeTab": "review"}
    assert values["people"] == {**expected_closed, "activeTab": "people"}
    assert values["places"] == {**expected_closed, "activeTab": "places"}
    assert values["enhance"] == {
        "action": "enhance",
        "activeTab": "ai",
        "browseOpen": False,
        "writeToolsOpen": False,
        "historyOpen": False,
    }
    assert values["writeKeepsState"] == {
        "action": "tab",
        "activeTab": "write",
        "browseOpen": True,
        "writeToolsOpen": True,
        "historyOpen": True,
    }
    assert values["unknown"] == "write"


def test_logbook_tab_chrome_sync_marks_active_panel_and_buttons():
    values = _node_eval(
        """
        import { syncLogbookTabChrome } from './static/js/logbook/tabs.js';

        function classList() {
          const set = new Set();
          return {
            toggle(name, force) {
              if (force) set.add(name);
              else set.delete(name);
            },
            contains(name) {
              return set.has(name);
            }
          };
        }

        function element({ dataset = {} } = {}) {
          return {
            dataset,
            attributes: {},
            classList: classList(),
            setAttribute(name, value) {
              this.attributes[name] = value;
            }
          };
        }

        const tabs = ['write', 'mood', 'data', 'review', 'people', 'places', 'ai']
          .map(tab => element({ dataset: { logbookTab: tab } }));
        const body = element();
        const browse = element();
        const more = element();
        const modal = {
          querySelectorAll(selector) {
            return selector === '[data-logbook-tab]' ? tabs : [];
          },
          querySelector(selector) {
            return ({
              '.logbook-body': body,
              '#logbook-toggle-browse': browse,
              '#logbook-toggle-write-more': more
            })[selector] || null;
          }
        };

        syncLogbookTabChrome(modal, {
          activeTab: 'people',
          browseOpen: true,
          writeToolsOpen: true
        });
        const peopleState = {
          activeTab: body.dataset.activeTab,
          peopleActive: tabs[4].classList.contains('active'),
          writeInactive: !tabs[0].classList.contains('active'),
          peopleSelected: tabs[4].attributes['aria-selected'],
          browseOpen: body.classList.contains('browse-open'),
          writeMoreOpen: body.classList.contains('write-more-open'),
          browseExpanded: browse.attributes['aria-expanded'],
          moreExpanded: more.attributes['aria-expanded']
        };

        syncLogbookTabChrome(modal, {
          activeTab: 'write',
          browseOpen: true,
          writeToolsOpen: true
        });
        const writeState = {
          activeTab: body.dataset.activeTab,
          writeActive: tabs[0].classList.contains('active'),
          peopleInactive: !tabs[4].classList.contains('active'),
          writeSelected: tabs[0].attributes['aria-selected'],
          browseOpen: body.classList.contains('browse-open'),
          writeMoreOpen: body.classList.contains('write-more-open'),
          browseExpanded: browse.attributes['aria-expanded'],
          moreExpanded: more.attributes['aria-expanded']
        };

        console.log(JSON.stringify({ peopleState, writeState }));
        """
    )

    assert values == {
        "peopleState": {
            "activeTab": "people",
            "peopleActive": True,
            "writeInactive": True,
            "peopleSelected": "true",
            "browseOpen": False,
            "writeMoreOpen": False,
            "browseExpanded": "false",
            "moreExpanded": "false",
        },
        "writeState": {
            "activeTab": "write",
            "writeActive": True,
            "peopleInactive": True,
            "writeSelected": "true",
            "browseOpen": True,
            "writeMoreOpen": True,
            "browseExpanded": "true",
            "moreExpanded": "true",
        },
    }
