export function fieldInput(field, escape) {
  const key = escape(field.key);
  if (field.type === 'select') {
    return `<select name="${key}">${field.choices.map(item => `<option${item === field.default ? ' selected' : ''}>${escape(item)}</option>`).join('')}</select>`;
  }
  if (field.type === 'str') return `<input name="${key}" value="${escape(field.default)}" required>`;
  return `<input type="number" name="${key}" value="${escape(field.default)}" step="${field.type === 'int' ? 1 : 'any'}" ${field.min == null ? '' : `min="${escape(field.min)}"`} ${field.max == null ? '' : `max="${escape(field.max)}"`} required>`;
}
