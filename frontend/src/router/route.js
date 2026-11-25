export function getRoute() {
  const [page,key] = location.hash.slice(1).split('/');
  const section = /^\d$/.test(page) && Number(page) < 6 ? Number(page) : 0;
  const runId = /^[1-9]\d*$/.test(key || '') ? Number(key) : null;
  return {section,runId};
}
