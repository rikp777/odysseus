export const MODAL_ID = 'logbook-modal';
export const SAVE_DELAY = 900;

export const MOODS = [
  { label: 'Bad', value: 'bad', score: 1 },
  { label: 'Meh', value: 'meh', score: 2 },
  { label: 'Okay', value: 'okay', score: 3 },
  { label: 'Good', value: 'good', score: 4 },
  { label: 'Great', value: 'great', score: 5 },
];

export const QUICK_DATA = [
  ['sleep', 'Sleep'],
  ['energy', 'Energy'],
  ['stress', 'Stress'],
  ['workout', 'Workout'],
  ['food', 'Food'],
  ['pain', 'Pain'],
  ['work', 'Work'],
  ['social', 'Social'],
  ['medication', 'Medication'],
  ['gratitude', 'Gratitude'],
];

export const LOGBOOK_TEMPLATES = [
  {
    key: 'workday',
    label: 'Workday',
    content: '## Focus\n\n\n\n## Wins\n\n\n\n## Stuck on\n\n\n\n## Tomorrow\n\n',
  },
  {
    key: 'workout',
    label: 'Workout',
    content: '## Workout\n\nMoved:\n\n\n\n## Notes\n\n\n\n## Recovery\n\n',
  },
  {
    key: 'social',
    label: 'Social',
    content: '## With\n\n\n\n## Notes\n\n',
  },
  {
    key: 'travel',
    label: 'Travel',
    content: '## Where\n\n\n\n## Highlights\n\n\n\n## Notes\n\n',
  },
  {
    key: 'evening',
    label: 'Evening',
    content: '## Wins today\n\n\n\n## Grateful for\n\n\n\n## Tomorrow\'s priority\n\n',
  },
  {
    key: 'illness',
    label: 'Illness',
    content: '## Symptoms\n\n\n\n## Treatment\n\n\n\n## Rest\n\n',
  },
];

