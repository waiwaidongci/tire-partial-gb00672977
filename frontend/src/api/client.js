import {state, session} from '../stores/session.js';

export async function request(path, payload, method) {
  const headers = state.token ? {Authorization: `Bearer ${state.token}`} : {};
  if (payload) headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api${path}`, {method: method || (payload ? 'POST' : 'GET'), headers, body: payload ? JSON.stringify(payload) : undefined});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && path !== '/login') session(null, null);
    const detail = Array.isArray(body.detail) ? '请核对必填项与数据格式。' : body.detail;
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return response;
}

export async function api(path, payload, method) {
  return (await request(path, payload, method)).json();
}

export async function download(path, name) {
  const blob = await (await request(path)).blob();
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement('a'), {href: url, download: name});
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
