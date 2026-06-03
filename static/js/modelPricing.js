// Shared frontend formatting for provider model pricing payloads.

function _formatUsd(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  if (n < 0.01) return `$${n.toFixed(3)}`;
  if (n < 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(2).replace(/\.00$/, '')}`;
}

function _shortUnit(unit) {
  const value = String(unit || '').toLowerCase();
  if (value.includes('character')) return '1M chars';
  if (value.includes('video')) return '1M video tok';
  if (value.includes('image')) return '1M image tok';
  if (value.includes('reranking')) return '1M rank tok';
  if (value.includes('token')) return '1M tok';
  return unit || 'unit';
}

export function formatModelPrice(pricing) {
  if (!pricing) return null;
  const input = pricing.input_usd_per_unit;
  const output = pricing.output_usd_per_unit;
  const unit = pricing.unit || '1M tokens';
  if (input != null && output != null) {
    const compact = `${_formatUsd(input)}/${_formatUsd(output)} · ${_shortUnit(unit)}`;
    const button = `${_formatUsd(input)}/${_formatUsd(output)}`;
    const detail = `Input ${_formatUsd(input)} / output ${_formatUsd(output)} per ${unit}`;
    return { compact, button, detail };
  }
  if (input != null) {
    const compact = `${_formatUsd(input)} in · ${_shortUnit(unit)}`;
    const button = `${_formatUsd(input)} in`;
    const detail = `Input ${_formatUsd(input)} per ${unit}`;
    return { compact, button, detail };
  }
  if (pricing.price_usd_per_unit != null) {
    const compact = `${_formatUsd(pricing.price_usd_per_unit)} · ${_shortUnit(unit)}`;
    const button = _formatUsd(pricing.price_usd_per_unit);
    const detail = `${_formatUsd(pricing.price_usd_per_unit)} per ${unit}`;
    return { compact, button, detail };
  }
  return null;
}
