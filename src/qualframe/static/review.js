(() => {
  const form = document.getElementById('decision-form');
  const source = document.getElementById('review-source');
  const feedback = document.getElementById('selection-feedback');
  const accept = document.getElementById('accept-button');
  const editControls = document.getElementById('edit-controls');
  let dirty = false, selection = null;

  // Time on this item, counting only while the page is visible (recorded with the decision).
  let visibleMs = 0, visibleSince = document.hidden ? null : performance.now();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && visibleSince !== null) { visibleMs += performance.now() - visibleSince; visibleSince = null; }
    else if (!document.hidden && visibleSince === null) { visibleSince = performance.now(); }
  });
  const secondsOnItem = () => (visibleMs + (visibleSince === null ? 0 : performance.now() - visibleSince)) / 1000;

  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('submit', () => {
    dirty = false;
    if (form.elements.seconds_on_item) form.elements.seconds_on_item.value = secondsOnItem().toFixed(1);
  });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });

  // Character offsets are counted in Unicode code points over the transcript text, matching the engine.
  document.addEventListener('selectionchange', () => {
    const chosen = window.getSelection();
    if (!chosen || chosen.isCollapsed || !chosen.rangeCount) return;
    const range = chosen.getRangeAt(0);
    if (!source.contains(range.startContainer) || !source.contains(range.endContainer)) return;
    const before = document.createRange(); before.selectNodeContents(source); before.setEnd(range.startContainer, range.startOffset);
    const through = document.createRange(); through.selectNodeContents(source); through.setEnd(range.endContainer, range.endOffset);
    selection = [Array.from(before.toString()).length, Array.from(through.toString()).length];
  });

  function useSelection() {
    if (!selection || selection[1] <= selection[0]) { feedback.textContent = 'Select a passage in the transcript first.'; return; }
    form.elements.edited_start.value = selection[0]; form.elements.edited_end.value = selection[1];
    const chars = Array.from(source.textContent);
    const mark = document.createElement('mark'); mark.id = 'current-span'; mark.textContent = chars.slice(...selection).join('');
    source.replaceChildren(document.createTextNode(chars.slice(0, selection[0]).join('')), mark, document.createTextNode(chars.slice(selection[1]).join('')));
    dirty = true;
    if (accept) accept.disabled = true;
    editControls.open = true;
    feedback.textContent = 'New passage selected. Choose Save change and continue to record it.';
  }
  document.getElementById('use-selection').addEventListener('click', useSelection);

  // Adding a code the model missed: the current transcript selection becomes a new coding.
  const addForm = document.getElementById('add-form');
  const addControls = document.getElementById('add-controls');
  const addFeedback = document.getElementById('add-feedback');
  const addPreview = document.getElementById('add-preview');
  function captureForAdd() {
    if (!addForm) return false;
    addControls.open = true;
    if (!selection || selection[1] <= selection[0]) {
      addFeedback.textContent = 'Select a passage in this transcript first, then choose its code.';
      return false;
    }
    addForm.elements.added_start.value = selection[0]; addForm.elements.added_end.value = selection[1];
    addPreview.textContent = Array.from(source.textContent).slice(...selection).join('');
    addPreview.hidden = false;
    addFeedback.textContent = 'Passage selected. Choose its code, then Add code.';
    return true;
  }
  if (addForm) {
    addControls.addEventListener('toggle', () => { if (addControls.open && selection) captureForAdd(); });
    document.addEventListener('mouseup', () => setTimeout(() => { if (addControls.open && selection) captureForAdd(); }, 0));
    addForm.addEventListener('submit', event => {
      if (!addForm.elements.added_start.value && !captureForAdd()) event.preventDefault();
      else dirty = false;
    });
  }

  form.elements.edited_code_id.addEventListener('change', () => {
    if (accept) accept.disabled = true;
    feedback.textContent = 'Code changed. Choose Save change and continue to record it.';
  });

  const bookSearch = document.getElementById('book-search');
  if (bookSearch) bookSearch.addEventListener('input', event => {
    for (const entry of document.querySelectorAll('.code-entry')) entry.hidden = !entry.textContent.toLowerCase().includes(event.target.value.toLowerCase());
  });
  function filterQueue() {
    const query = document.getElementById('queue-search').value.toLowerCase();
    const state = document.getElementById('queue-filter').value;
    for (const row of document.querySelectorAll('#proposal-list li')) row.hidden = !row.textContent.toLowerCase().includes(query) || (state !== 'all' && row.dataset.status !== state);
  }
  document.getElementById('queue-search').addEventListener('input', filterQueue);
  document.getElementById('queue-filter').addEventListener('change', filterQueue);

  // Keyboard shortcuts, ignored while typing.
  function click(id) { const el = document.getElementById(id); if (el && !el.disabled) { dirty = false; el.click(); } }
  document.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const tag = (event.target.tagName || '').toLowerCase();
    if (['input', 'textarea', 'select'].includes(tag) || event.target.isContentEditable) return;
    const key = event.key.toLowerCase();
    const actions = {
      a: () => click('accept-button'), r: () => click('reject-button'), l: () => click('defer-button'),
      c: () => { editControls.open = true; document.getElementById('code-select').focus(); },
      u: useSelection,
      n: () => { captureForAdd(); document.getElementById('add-code-select').focus(); },
      j: () => { const n = document.getElementById('next-link'); if (n) location.href = n.href; },
      k: () => { const p = document.getElementById('prev-link'); if (p) location.href = p.href; },
    };
    if (actions[key]) { event.preventDefault(); actions[key](); }
  });

  // Bring the highlighted passage into view inside the transcript, and the current item into view in the list.
  const mark = document.getElementById('current-span');
  if (mark) {
    // Place the passage about a third of the way down, so the lines before it give context.
    const box = source.getBoundingClientRect();
    const visible = Math.min(box.bottom, window.innerHeight) - Math.max(box.top, 0);
    const lead = Math.max(48, Math.round(Math.min(source.clientHeight, visible) / 3));
    source.scrollTop += mark.getBoundingClientRect().top - source.getBoundingClientRect().top - lead;
  }
  const current = document.querySelector('#proposal-list a[aria-current=true]');
  const rail = document.querySelector('.proposal-rail');
  if (current && rail && rail.scrollHeight > rail.clientHeight) {
    rail.scrollTop += current.getBoundingClientRect().top - rail.getBoundingClientRect().top - rail.clientHeight / 2;
  }
})();
