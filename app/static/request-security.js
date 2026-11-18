(() => {
  'use strict';
  const token = () => document.querySelector('meta[name="csrf-token"]')?.content || '';
  const unsafe = method => !['GET', 'HEAD', 'OPTIONS'].includes(String(method || 'GET').toUpperCase());
  const local = value => new URL(value, document.baseURI).origin === window.location.origin;
  const originalFetch = window.fetch;
  window.fetch = function (input, init = {}) {
    init = init || {};
    const url = input instanceof Request ? input.url : String(input);
    const method = init.method || (input instanceof Request ? input.method : 'GET');
    if (unsafe(method) && local(url)) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-CSRF-Token', token());
      return originalFetch.call(this, input, {...init, headers});
    }
    return originalFetch.call(this, input, init);
  };
  function protect(form, submitter) {
    const action = submitter?.hasAttribute('formaction') ? submitter.formAction : form.action || location.href;
    const method = submitter?.hasAttribute('formmethod') ? submitter.formMethod : form.method;
    if (!unsafe(method) || !local(action)) return;
    let field = form.querySelector('input[name="csrf_token"]');
    if (!field) {
      field = document.createElement('input');
      field.type = 'hidden';
      field.name = 'csrf_token';
      form.append(field);
    }
    field.value = token();
  }
  document.addEventListener('submit', event => {
    if (event.target instanceof HTMLFormElement) protect(event.target, event.submitter);
  }, true);
  for (const name of ['submit', 'requestSubmit']) {
    const nativeMethod = HTMLFormElement.prototype[name];
    if (!nativeMethod) continue;
    HTMLFormElement.prototype[name] = function (...args) {
      protect(this, name === 'requestSubmit' ? args[0] : undefined);
      return nativeMethod.apply(this, args);
    };
  }
})();
