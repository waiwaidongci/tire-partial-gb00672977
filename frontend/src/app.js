import {api} from './api/client.js';
import {empty,login,shell} from './components/common/layout.js';
import {bindForm} from './hooks/forms.js';
import {analysis,bindAnalysis,results} from './pages/analysis.js';
import {bindDispatch,delivery,review} from './pages/dispatch.js';
import {bindSource,overview,source} from './pages/source.js';
import {getRoute} from './router/route.js';
import {session,state} from './stores/session.js';
import {esc,formData} from './utils/html.js';

const root = document.querySelector('#app');
const pages = [overview,source,analysis,results,review,delivery];
let tick;
let generation = 0;

async function render() {
  clearTimeout(tick);
  const current = ++generation;
  if (!state.account) {
    root.innerHTML = login();
    bindForm(root,'#login',async form => {
      const result = await api('/login',formData(form));
      session(result.token,result.account);
    },render);
    return;
  }
  const {section,runId} = getRoute();
  state.runId = runId;
  try {
    const content = await pages[section]();
    if (current !== generation) return;
    root.innerHTML = shell(section,content);
    state.status = '';
    root.querySelector('#logout').addEventListener('click',() => {session(null,null); render();});
    bindSource(root,render);
    bindAnalysis(root,section,render);
    bindDispatch(root,render);
    if (root.querySelector('[data-poll]')) tick = setTimeout(render,850);
  } catch (error) {
    if (current !== generation) return;
    if (!state.account) return render();
    root.innerHTML = shell(section,empty(error.message));
    root.querySelector('#logout').addEventListener('click',() => {session(null,null); render();});
  }
}

try {
  state.profile = await api('/profile');
  document.title = state.profile.title;
  if (state.token) {
    try {state.account = await api('/me');}
    catch {session(null,null);}
  }
  window.addEventListener('hashchange',render);
  await render();
} catch (error) {
  root.innerHTML = `<main><p role="alert">${esc(error.message)}</p><button onclick="location.reload()">重新载入</button></main>`;
}
