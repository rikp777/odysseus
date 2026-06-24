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


def test_logbook_review_panel_renders_empty_and_populated_states():
    values = _node_eval(
        """
        import { renderReviewPanelHtml } from './static/js/logbook/review-panel.js';

        const empty = renderReviewPanelHtml({
          review: { range: { start: '2026-06-01', end: '2026-06-07', days: 7 }, stats: {} },
          period: 'week'
        });
        const populated = renderReviewPanelHtml({
          period: 'month',
          review: {
            range: { start: '2026-06-01', end: '2026-06-30', days: 30 },
            stats: { entry_count: 2, days_with_entries: 2, range_days: 30, people_count: 1, place_count: 1, datapoint_count: 2 },
            scores: { mood: { count: 2, average: 3 }, energy: { count: 2, average: 3.5 }, stress: { count: 2, average: 2 } },
            moods: [{ label: 'good', count: 1 }],
            datapoints: [{ key: 'sleep', label: 'Sleep', count: 2, numeric_count: 2, average: 6, latest_value: '7h', unit: 'h' }],
            insights: [{
              id: 'low_energy',
              level: 'warning',
              title: 'Energy ran low',
              detail: 'Average energy was 2/5 across 2 logged days.',
              evidence: [{ date: '2026-06-04', label: 'Energy', value: 2, unit: '/5', snippet: 'Coffee with Nora.' }]
            }],
            top_people: [{ display_name: 'Nora', count: 2, last_mentioned: '2026-06-04' }],
            top_places: [{ display_name: 'Gym', count: 1, last_mentioned: '2026-06-02' }],
            reconnect_candidates: [{ display_name: 'Old Friend', message: 'Maybe reach out.' }],
            highlights: [{ date: '2026-06-04', snippet: 'Coffee with Nora.', people: ['Nora'], places: ['Gym'] }]
          }
        });

        console.log(JSON.stringify({
          emptyHasMessage: empty.includes('No entries in this range yet.'),
          populatedHasMonthActive: populated.includes('data-logbook-review-period="month">Month</button>'),
          populatedHasSleep: populated.includes('Sleep'),
          populatedHasInsight: populated.includes('Energy ran low') && populated.includes('data-level="warning"'),
          populatedHasEvidenceDate: populated.includes('class="logbook-review-evidence" data-date="2026-06-04"'),
          populatedHasHighlightDate: populated.includes('data-date="2026-06-04"'),
          populatedEscapes: renderReviewPanelHtml({
            review: {
              stats: { entry_count: 1 },
              insights: [{ title: '<bad>', detail: '<detail>', evidence: [{ date: '2026-06-01', label: '<metric>' }] }],
              highlights: [{ date: '2026-06-01', snippet: '<raw>' }]
            }
          }).includes('&lt;bad&gt;') && renderReviewPanelHtml({
            review: {
              stats: { entry_count: 1 },
              insights: [{ title: '<bad>', detail: '<detail>', evidence: [{ date: '2026-06-01', label: '<metric>' }] }],
              highlights: [{ date: '2026-06-01', snippet: '<raw>' }]
            }
          }).includes('&lt;raw&gt;')
        }));
        """
    )

    assert values == {
        "emptyHasMessage": True,
        "populatedHasMonthActive": True,
        "populatedHasSleep": True,
        "populatedHasInsight": True,
        "populatedHasEvidenceDate": True,
        "populatedHasHighlightDate": True,
        "populatedEscapes": True,
    }
