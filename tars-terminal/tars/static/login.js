'use strict';
(() => {
  let signup = false;
  const form = document.getElementById('auth');
  const error = document.getElementById('error');
  const submit = document.getElementById('submit');

  // Hardened redirect: only allow a fixed set of in-app paths. Anything else
  // (absolute URLs, protocol-relative //evil.com, unknown paths) -> /beta.
  const ALLOWED_NEXT = new Set(['/', '/beta']);
  function destination() {
    const n = new URLSearchParams(location.search).get('next') || '/beta';
    return ALLOWED_NEXT.has(n) ? n : '/beta';
  }

  function mode(value) {
    signup = value;
    error.textContent = '';
    document.getElementById('signin').setAttribute('aria-pressed', String(!value));
    document.getElementById('signup').setAttribute('aria-pressed', String(value));
    document.getElementById('confirm-label').hidden = !value;
    form.elements.confirm.required = value;
    form.elements.password.autocomplete = value ? 'new-password' : 'current-password';
    submit.textContent = value ? '가입하고 시작하기' : '로그인하고 시작하기';
  }
  document.getElementById('signin').onclick = () => mode(false);
  document.getElementById('signup').onclick = () => mode(true);

  form.onsubmit = async (e) => {
    e.preventDefault();
    error.textContent = '';
    if (signup && form.elements.password.value !== form.elements.confirm.value) {
      error.textContent = '비밀번호가 일치하지 않습니다.';
      return;
    }
    submit.disabled = true;
    try {
      const r = await fetch('/api/personal/' + (signup ? 'register' : 'login'), {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: form.elements.username.value,
          password: form.elements.password.value,
        }),
        signal: AbortSignal.timeout(20000),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || '요청 실패');
      location.replace(destination());
    } catch (e) {
      error.textContent = e.name === 'TimeoutError'
        ? '응답이 늦습니다. 잠시 후 다시 시도해주세요.' : e.message;
    } finally {
      submit.disabled = false;
    }
  };

  // Already logged in? skip the gate.
  fetch('/api/personal/session', { cache: 'no-store' })
    .then(r => r.json())
    .then(s => { if (s.authenticated) location.replace(destination()); })
    .catch(() => {});
})();
