import {roles} from '../../constants/enums.js';
import {state} from '../../stores/session.js';
import {esc} from '../../utils/html.js';

export const empty = (detail, target, button) => `<div class="empty"><p>${esc(detail)}</p>${target ? `<a class="button" href="${target}">${esc(button)}</a>` : ''}</div>`;
export const errorSlot = '<p class="error" role="alert" data-error></p>';

export function shell(section, contents) {
  const profile = state.profile;
  return `<div class="workspace"><aside><header><p>${esc(profile.organization)}</p><strong>${esc(profile.title)}</strong></header><nav aria-label="业务模块">${profile.modules.map((title,index) => `<a href="#${index}" ${index === section ? 'aria-current="page"' : ''}>${esc(title)}</a>`).join('')}</nav><footer><span>${roles[state.account.role]} · ${esc(state.account.username)}</span><button type="button" id="logout" class="secondary">退出</button></footer></aside><main><header class="page-head"><div><p class="kicker">${esc(profile.direction)}</p><h1>${esc(profile.modules[section])}</h1></div><span>${esc(profile.id)}</span></header>${state.status ? `<p role="status" class="notice">${esc(state.status)}</p>` : ''}<div class="page">${contents}</div></main></div>`;
}

export function login() {
  const {title, organization, context} = state.profile;
  return `<main class="login"><div class="login-context"><p class="kicker">${esc(organization)}</p><h1>${esc(title)}</h1><p>${esc(context)}</p></div><form id="login"><h2>登录</h2><label>账号<input name="username" autocomplete="username" required></label><label>密码<input name="password" type="password" autocomplete="current-password" required></label><button type="submit">进入工作区</button>${errorSlot}<p class="hint">演示账号 analyst、reviewer、viewer<br>密码格式为账号加 -demo-24</p></form></main>`;
}
