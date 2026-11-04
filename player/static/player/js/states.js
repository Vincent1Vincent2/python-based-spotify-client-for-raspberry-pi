function renderState(el, kind, message) {
    if (!el) {
        return;
    }
    var state = kind === 'loading' || kind === 'empty' || kind === 'error' ? kind : 'empty';
    var titles = {
        loading: 'Loading',
        empty: 'Empty',
        error: 'Error'
    };
    var panel = document.createElement('div');
    panel.className = 'state-panel state-' + state;
    panel.setAttribute('role', state === 'error' ? 'alert' : 'status');

    var title = document.createElement('p');
    title.className = 'state-title';
    title.textContent = titles[state];

    var detail = document.createElement('p');
    detail.className = 'state-message';
    detail.textContent = message == null ? '' : String(message);

    panel.appendChild(title);
    panel.appendChild(detail);
    el.replaceChildren(panel);
}
