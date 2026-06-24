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


def test_logbook_followups_panel_renders_actions_and_escapes():
    values = _node_eval(
        """
        import { renderFollowupsHtml } from './static/js/logbook/followups-panel.js';

        const empty = renderFollowupsHtml({ followups: [], counts: { active: 0 } });
        const populated = renderFollowupsHtml({
          counts: { active: 1 },
          followups: [{
            id: 'p1',
            status: 'active',
            level: 'overdue',
            display_name: 'Old <Friend>',
            relationship_label: 'friend',
            message: 'Maybe send <message>.',
            last_mentioned: '2026-04-01',
            days_since_mentioned: 70,
            contact_methods: [{ type: 'email', value: 'old@example.test' }],
            accepted_connections: 2,
            suggested_connections: 1
          }]
        });
        const snoozed = renderFollowupsHtml({
          followups: [{
            id: 'p2',
            status: 'snoozed',
            suppression: { until: '2026-06-24' },
            display_name: 'Nora',
            message: 'Later.'
          }]
        });

        console.log(JSON.stringify({
          emptyMessage: empty.includes('No active follow-ups right now.'),
          hasSnooze: populated.includes('data-followup-snooze="p1"'),
          hasDismiss: populated.includes('data-followup-dismiss="p1"'),
          hasOpen: populated.includes('data-followup-open="p1"'),
          hasConnections: populated.includes('2 accepted | 1 suggested'),
          escapesNameAndMessage: populated.includes('Old &lt;Friend&gt;') && populated.includes('Maybe send &lt;message&gt;.'),
          snoozedRestore: snoozed.includes('Snoozed until 2026-06-24') && snoozed.includes('data-followup-restore="p2"')
        }));
        """
    )

    assert values == {
        "emptyMessage": True,
        "hasSnooze": True,
        "hasDismiss": True,
        "hasOpen": True,
        "hasConnections": True,
        "escapesNameAndMessage": True,
        "snoozedRestore": True,
    }
