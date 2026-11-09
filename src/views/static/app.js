// httpgo — progressive enhancement only; every page works without JS.
(function () {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function filterRows(rows, query) {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    let visible = 0;
    rows.forEach((row) => {
      const hay = row.dataset.search || '';
      const match = terms.every((t) => hay.includes(t));
      row.hidden = !match;
      if (match) visible++;
    });
    return visible;
  }

  function isTyping(e) {
    const el = e.target;
    return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
  }

  // ---- Directory: command palette ------------------------------------

  const palette = $('[data-palette]');
  if (palette) {
    const input = $('#search', palette);
    const rows = $$('.result', palette);
    const count = $('[data-count]', palette);
    const empty = $('[data-empty]', palette);
    let active = -1;

    const visibleRows = () => rows.filter((r) => !r.hidden);

    function setActive(index) {
      const vis = visibleRows();
      rows.forEach((r) => r.classList.remove('active'));
      if (!vis.length) {
        active = -1;
        input.setAttribute('aria-activedescendant', '');
        return;
      }
      active = Math.max(0, Math.min(index, vis.length - 1));
      const row = vis[active];
      row.classList.add('active');
      input.setAttribute('aria-activedescendant', row.id);
      row.scrollIntoView({ block: 'nearest' });
    }

    function update() {
      const q = input.value.trim();
      const n = filterRows(rows, q);
      count.textContent = q ? `${n} of ${rows.length}` : `${rows.length} link${rows.length === 1 ? '' : 's'}`;
      if (empty && rows.length) empty.hidden = n > 0;
      const create = empty && $('[data-create]', empty);
      if (create) {
        const name = q.toLowerCase().replace(/\s+/g, '-');
        create.href = `/admin/?new=${encodeURIComponent(/^[a-z0-9][a-z0-9_-]*$/.test(name) ? name : '')}`;
        create.textContent = n === 0 && q ? `Create go/${name}` : 'New link';
      }
      setActive(q ? 0 : -1);
    }

    input.addEventListener('input', update);
    input.addEventListener('keydown', (e) => {
      const vis = visibleRows();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive(active + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive(active - 1);
      } else if (e.key === 'Enter') {
        const q = input.value.trim().toLowerCase();
        // Exact name match wins, then the highlighted row, then "go/<query>"
        // so typing a path like "jira/ABC-1" still works.
        const exact = vis.find((r) => r.id === `r-${q}`);
        const target = exact || vis[active] || vis[0];
        if (target) {
          window.location.href = $('a', target).href;
        } else if (q) {
          window.location.href = '/' + q.split('/').map(encodeURIComponent).join('/');
        }
      } else if (e.key === 'Escape') {
        input.value = '';
        update();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !isTyping(e)) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    });

    if (input.value) update();
  }

  // ---- Admin: filter ---------------------------------------------------

  const filter = $('[data-filter]');
  if (filter) {
    const rows = $$('[data-row]');
    filter.addEventListener('input', () => filterRows(rows, filter.value.trim()));
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !isTyping(e)) {
        e.preventDefault();
        filter.focus();
      }
    });
  }

  // ---- Admin: new/edit slide-over -------------------------------------

  const dialog = $('#link-dialog');
  if (dialog) {
    const form = $('form', dialog);
    const title = $('#dialog-title', dialog);
    const submit = $('[data-submit]', dialog);
    const fields = {
      shortname: $('#f-shortname', dialog),
      url: $('#f-url', dialog),
      description: $('#f-description', dialog),
    };

    function open(mode, data = {}) {
      const editing = mode === 'edit';
      form.action = editing
        ? dialog.dataset.editAction.replace('__name__', encodeURIComponent(data.shortname))
        : dialog.dataset.newAction;
      title.textContent = editing ? 'Edit link' : 'New link';
      submit.textContent = editing ? 'Save changes' : 'Create link';
      fields.shortname.readOnly = editing;
      if (data.shortname !== undefined) fields.shortname.value = data.shortname;
      if (data.url !== undefined) fields.url.value = data.url;
      if (data.description !== undefined) fields.description.value = data.description;
      dialog.showModal();
      (editing || fields.shortname.value ? fields.url : fields.shortname).focus();
    }

    $$('[data-open-new]').forEach((btn) =>
      btn.addEventListener('click', () => open('new', { shortname: '', url: '', description: '' })));

    $$('[data-edit]').forEach((btn) =>
      btn.addEventListener('click', () => open('edit', {
        shortname: btn.dataset.shortname,
        url: btn.dataset.url,
        description: btn.dataset.description,
      })));

    $$('[data-close]', dialog).forEach((btn) => btn.addEventListener('click', () => dialog.close()));
    dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'n' && !isTyping(e) && !dialog.open && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        open('new', { shortname: '', url: '', description: '' });
      }
    });

    if (dialog.dataset.reopen === 'new') {
      open('new'); // keep values the server echoed back after a validation error
    } else if (dialog.dataset.prefill !== undefined) {
      open('new', { shortname: dialog.dataset.prefill, url: '', description: '' });
      history.replaceState(null, '', location.pathname);
    }
  }

  // ---- Confirm destructive forms --------------------------------------

  $$('form[data-confirm]').forEach((form) =>
    form.addEventListener('submit', (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    }));
})();

// ---- Settings: copy token ---------------------------------------------
(function () {
  'use strict';
  document.querySelectorAll('[data-copy]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const input = document.querySelector(btn.dataset.copy);
      input.select();
      try {
        await navigator.clipboard.writeText(input.value);
      } catch {
        document.execCommand('copy'); // clipboard API needs HTTPS; http://go/ isn't
      }
      btn.textContent = 'Copied';
      setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
    });
  });
  document.querySelectorAll('[data-select-on-focus]').forEach((el) =>
    el.addEventListener('focus', () => el.select()));
})();
