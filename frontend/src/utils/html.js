export const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[char]);
export const time = value => value ? new Intl.DateTimeFormat('zh-CN', {dateStyle:'short', timeStyle:'short'}).format(value * 1000) : '—';
export const formData = element => Object.fromEntries(new FormData(element));

const decimal = new Intl.NumberFormat('zh-CN',{maximumFractionDigits:6,useGrouping:false});
export function display(value) {
  if (typeof value !== 'number' || Number.isInteger(value)) return value;
  return value && Math.abs(value) < 0.000001 ? value.toExponential(3) : decimal.format(value);
}
