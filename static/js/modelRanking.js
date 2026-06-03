// Lightweight client-side model ranking for admin list sorting.
// Providers do not expose a standard "intelligence" field, so this estimates
// capability from common model-family names, size markers, and tier suffixes.

const FAMILY_HINTS = [
  [/opus|o1-pro|gpt[-_. ]?5.*pro|gpt[-_. ]?4\.5|claude.*4.*opus/i, 95],
  [/sonnet|gpt[-_. ]?5|o3|o4|deepseek[-_. ]?r1|deepseek.*pro|qwen3\.5|kimi[-_. ]?k2|llama[-_. ]?4.*maverick/i, 85],
  [/gpt[-_. ]?4o|gpt[-_. ]?4\.1|nemotron|qwen3|glm[-_. ]?5|llama[-_. ]?4.*scout/i, 75],
  [/haiku|gemma|mistral|llama3|llama[-_. ]?3|deepseek|qwen/i, 62],
  [/embedding|rerank|tts|whisper|image|diffusion|video|router:/i, 30],
];

const MODIFIER_HINTS = [
  [/pro|max|opus|reason|thinking|r1/i, 12],
  [/coder|code/i, 6],
  [/large|120b|397b|235b|70b/i, 5],
  [/medium|32b|31b/i, 2],
  [/small|mini|flash|nano|8b|14b/i, -8],
  [/embedding|rerank|tts|whisper|image|diffusion|video|router:/i, -18],
];

function _modelText(model) {
  if (typeof model === 'string') return model;
  return String(model?.id || model?.mid || model?.name || model?.display || model?.model || '');
}

function _sizeScore(text) {
  const matches = [...text.matchAll(/(\d+(?:\.\d+)?)\s*b\b/gi)]
    .map(match => Number(match[1]))
    .filter(Number.isFinite);
  if (!matches.length) return 0;
  const max = Math.max(...matches);
  if (max >= 300) return 12;
  if (max >= 120) return 9;
  if (max >= 70) return 6;
  if (max >= 30) return 3;
  if (max <= 14) return -3;
  return 0;
}

export function modelIntelligenceScore(model) {
  const text = _modelText(model);
  if (!text) return 0;
  let score = 50;
  for (const [pattern, value] of FAMILY_HINTS) {
    if (pattern.test(text)) {
      score = value;
      break;
    }
  }
  for (const [pattern, value] of MODIFIER_HINTS) {
    if (pattern.test(text)) score += value;
  }
  score += _sizeScore(text);
  return Math.max(0, Math.min(100, score));
}

export function modelIntelligenceLabel(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) return 'Unknown';
  if (value >= 88) return 'Top';
  if (value >= 74) return 'High';
  if (value >= 58) return 'Medium';
  if (value >= 38) return 'Basic';
  return 'Utility';
}
