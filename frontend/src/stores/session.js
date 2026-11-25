export const state = {profile: null, account: null, token: sessionStorage.getItem('token'), runId: null, datasetId: null, status: ''};

export function session(token, account) {
  state.token = token;
  state.account = account;
  if (token) sessionStorage.setItem('token', token);
  else sessionStorage.removeItem('token');
}
