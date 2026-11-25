import {state} from '../stores/session.js';

export function bindForm(root, id, submit, refresh) {
  root.querySelector(id)?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const buttons = [...form.querySelectorAll('button[type=submit]')];
    buttons.forEach(button => {button.disabled = true;});
    const message = form.querySelector('[data-error]');
    if (message) message.textContent = '';
    try {
      await submit(form, event.submitter);
      if (refresh) await refresh();
    } catch (error) {
      if (!state.account && id !== '#login') {await refresh(); return;}
      if (message) message.textContent = error.message;
    } finally {
      buttons.forEach(button => {button.disabled = false;});
    }
  });
}
