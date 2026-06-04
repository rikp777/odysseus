export const CLOUD_BILLING_PROVIDER_HINTS = {
  digitalocean: 'DigitalOcean token with billing:read and account:read',
  openai: 'OpenAI admin key with organization usage/costs access',
  anthropic: 'Anthropic Admin API key',
};

export const CLOUD_BILLING_PROVIDER_LABELS = {
  digitalocean: 'DigitalOcean',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
};

export function providerHint(provider) {
  return CLOUD_BILLING_PROVIDER_HINTS[provider] || 'Provider billing API token';
}

export function providerOptions(selected, escapeHtml) {
  return Object.keys(CLOUD_BILLING_PROVIDER_LABELS).map(function(provider) {
    return '<option value="' + escapeHtml(provider) + '"' + (provider === selected ? ' selected' : '') + '>' +
      escapeHtml(CLOUD_BILLING_PROVIDER_LABELS[provider]) +
      '</option>';
  }).join('');
}
