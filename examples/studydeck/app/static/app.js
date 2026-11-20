'use strict';

const appEl = document.getElementById('app');
const statsBarEl = document.getElementById('stats-bar');

const GRADE_KEYS = { '1': 'again', '2': 'hard', '3': 'good', '4': 'easy' };

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll(String.fromCharCode(34), '&quot;')
    .replaceAll(String.fromCharCode(39), '&#39;');
}

async function api(path, { method = 'GET', body } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch (err) {
    data = null;
  }
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : `Request failed (${response.status})`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

function parseRoute() {
  const hash = window.location.hash || '#/';
  if (hash.startsWith('#/deck/')) {
    return { view: 'deck', id: Number(hash.slice('#/deck/'.length)) };
  }
  if (hash.startsWith('#/study/')) {
    return { view: 'study', id: Number(hash.slice('#/study/'.length)) };
  }
  return { view: 'decks' };
}

async function refreshStatsBar() {
  try {
    const stats = await api('/api/stats');
    const total = typeof stats.total_reviewed_today === 'number'
      ? stats.total_reviewed_today
      : (stats.decks || []).reduce((sum, deck) => sum + (deck.reviewed_today || 0), 0);
    const streak = stats.streak || 0;
    statsBarEl.innerHTML = `
      <span class='stat-pill'>🔥 Streak: <strong>${streak}</strong> day${streak === 1 ? '' : 's'}</span>
      <span class='stat-pill'>✅ Reviewed today: <strong>${total}</strong></span>
    `;
  } catch (err) {
    statsBarEl.innerHTML = '';
  }
}

function showError(message) {
  appEl.innerHTML = `<p class='error'>${escapeHtml(message)}</p><p><a href='#/'>← Back to decks</a></p>`;
}

async function render() {
  window.onkeydown = null;
  const route = parseRoute();
  try {
    if (route.view === 'deck') {
      await renderDeck(route.id);
    } else if (route.view === 'study') {
      await renderStudy(route.id);
    } else {
      await renderDeckList();
    }
  } catch (err) {
    showError(err.message || 'Something went wrong');
  }
  refreshStatsBar();
}

async function renderDeckList() {
  appEl.innerHTML = `<p class='muted'>Loading decks…</p>`;
  const [decks, stats] = await Promise.all([api('/api/decks'), api('/api/stats')]);
  const total = typeof stats.total_reviewed_today === 'number'
    ? stats.total_reviewed_today
    : (stats.decks || []).reduce((sum, deck) => sum + (deck.reviewed_today || 0), 0);
  const streak = stats.streak || 0;
  statsBarEl.innerHTML = `
    <span class='stat-pill'>🔥 Streak: <strong>${streak}</strong> day${streak === 1 ? '' : 's'}</span>
    <span class='stat-pill'>✅ Reviewed today: <strong>${total}</strong></span>
  `;

  let html = `
    <section class='card create-card'>
      <h2>Create a deck</h2>
      <form id='create-deck-form' class='stack'>
        <label>
          Deck name
          <input name='name' maxlength='80' required placeholder='e.g. Spanish vocabulary'>
        </label>
        <label>
          Description <span class='muted'>(optional, up to 300 characters)</span>
          <textarea name='description' maxlength='300' rows='2' placeholder='What is this deck for?'></textarea>
        </label>
        <button type='submit' class='button primary'>Create deck</button>
      </form>
    </section>
  `;

  if (!decks.length) {
    html += `<p class='muted'>No decks yet. Create your first deck above.</p>`;
  } else {
    html += `<div class='deck-list'>`;
    for (const deck of decks) {
      html += `
        <article class='deck-item card'>
          <div class='deck-main'>
            <h2><a href='#/deck/${deck.id}'>${escapeHtml(deck.name)}</a></h2>
            ${deck.description ? `<p class='muted'>${escapeHtml(deck.description)}</p>` : ''}
            <p class='deck-meta'>
              <span>${deck.card_count} card${deck.card_count === 1 ? '' : 's'}</span>
              <span>${deck.due_count} due today</span>
            </p>
          </div>
          <div class='deck-actions'>
            <a class='button' href='#/deck/${deck.id}'>Open</a>
            <a class='button primary' href='#/study/${deck.id}'>Study (${deck.due_count})</a>
            <button class='button' data-action='rename' data-id='${deck.id}'>Rename</button>
            <button class='button' data-action='describe' data-id='${deck.id}'>Edit description</button>
            <button class='button danger' data-action='delete' data-id='${deck.id}'>Delete</button>
          </div>
        </article>
      `;
    }
    html += `</div>`;
  }

  appEl.innerHTML = html;

  const form = document.getElementById('create-deck-form');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = form.elements.name.value.trim();
    const description = form.elements.description.value.trim();
    if (!name) {
      alert('Deck name is required.');
      return;
    }
    try {
      await api('/api/decks', {
        method: 'POST',
        body: { name, description: description || null },
      });
      form.reset();
      await renderDeckList();
      refreshStatsBar();
    } catch (err) {
      alert(err.message);
    }
  });

  appEl.querySelectorAll('button[data-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const id = Number(button.dataset.id);
      const deck = decks.find((item) => item.id === id);
      if (!deck) return;
      if (button.dataset.action === 'rename') {
        const nextName = prompt('Rename deck', deck.name);
        if (nextName === null) return;
        const name = nextName.trim();
        if (!name) {
          alert('Deck name is required.');
          return;
        }
        try {
          await api(`/api/decks/${id}`, { method: 'PATCH', body: { name } });
          await renderDeckList();
        } catch (err) {
          alert(err.message);
        }
      } else if (button.dataset.action === 'describe') {
        const next = prompt('Deck description (leave empty to remove it)', deck.description || '');
        if (next === null) return;
        const description = next.trim();
        if (description.length > 300) {
          alert('The description can be at most 300 characters.');
          return;
        }
        try {
          await api(`/api/decks/${id}`, {
            method: 'PATCH',
            body: { description: description || null },
          });
          await renderDeckList();
        } catch (err) {
          alert(err.message);
        }
      } else if (button.dataset.action === 'delete') {
        if (!confirm(`Delete '${deck.name}' and all of its cards?`)) return;
        try {
          await api(`/api/decks/${id}`, { method: 'DELETE' });
          await renderDeckList();
          refreshStatsBar();
        } catch (err) {
          alert(err.message);
        }
      }
    });
  });
}

async function renderDeck(deckId) {
  appEl.innerHTML = `<p class='muted'>Loading deck…</p>`;
  const [decks, cards] = await Promise.all([
    api('/api/decks'),
    api(`/api/decks/${deckId}/cards`),
  ]);
  const deck = decks.find((item) => item.id === deckId);
  if (!deck) throw new Error('Deck not found');

  let html = `
    <a href='#/' class='back-link'>← All decks</a>
    <section class='card deck-header'>
      <div>
        <h2>${escapeHtml(deck.name)}</h2>
        ${deck.description ? `<p class='muted'>${escapeHtml(deck.description)}</p>` : ''}
        <p class='deck-meta'>
          <span>${deck.card_count} card${deck.card_count === 1 ? '' : 's'}</span>
          <span>${deck.due_count} due today</span>
        </p>
      </div>
      <a class='button primary' href='#/study/${deck.id}'>Study now (${deck.due_count} due)</a>
    </section>

    <section class='card add-card'>
      <h3>Add a card</h3>
      <form id='add-card-form' class='stack'>
        <label>
          Front
          <textarea name='front' maxlength='500' rows='2' required placeholder='Question or prompt'></textarea>
        </label>
        <label>
          Back
          <textarea name='back' maxlength='500' rows='2' required placeholder='Answer or definition'></textarea>
        </label>
        <button type='submit' class='button primary'>Add card</button>
      </form>
    </section>
  `;

  if (!cards.length) {
    html += `<p class='muted'>No cards in this deck yet.</p>`;
  } else {
    html += `<section class='cards'>`;
    for (const card of cards) {
      html += `
        <article class='card card-item'>
          <div class='card-side'>
            <div class='label'>Front</div>
            <div class='card-text'>${escapeHtml(card.front)}</div>
          </div>
          <div class='card-side'>
            <div class='label'>Back</div>
            <div class='card-text'>${escapeHtml(card.back)}</div>
          </div>
          <p class='muted small'>Due ${escapeHtml(card.due_date)} · interval ${card.interval_days} day${card.interval_days === 1 ? '' : 's'} · ease ${Number(card.ease).toFixed(2)} · reps ${card.repetitions}</p>
          <div class='deck-actions'>
            <button class='button' data-card-action='edit' data-card-id='${card.id}'>Edit</button>
            <button class='button danger' data-card-action='delete' data-card-id='${card.id}'>Delete</button>
          </div>
        </article>
      `;
    }
    html += `</section>`;
  }

  appEl.innerHTML = html;

  const addForm = document.getElementById('add-card-form');
  addForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const front = addForm.elements.front.value.trim();
    const back = addForm.elements.back.value.trim();
    if (!front || !back) {
      alert('Front and back are required.');
      return;
    }
    try {
      await api(`/api/decks/${deckId}/cards`, {
        method: 'POST',
        body: { front, back },
      });
      await renderDeck(deckId);
      refreshStatsBar();
    } catch (err) {
      alert(err.message);
    }
  });

  appEl.querySelectorAll('button[data-card-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const cardId = Number(button.dataset.cardId);
      const card = cards.find((item) => item.id === cardId);
      if (!card) return;
      if (button.dataset.cardAction === 'edit') {
        const front = prompt('Front text', card.front);
        if (front === null) return;
        const back = prompt('Back text', card.back);
        if (back === null) return;
        if (!front.trim() || !back.trim()) {
          alert('Front and back are required.');
          return;
        }
        try {
          await api(`/api/cards/${cardId}`, {
            method: 'PATCH',
            body: { front: front.trim(), back: back.trim() },
          });
          await renderDeck(deckId);
        } catch (err) {
          alert(err.message);
        }
      } else if (button.dataset.cardAction === 'delete') {
        if (!confirm('Delete this card?')) return;
        try {
          await api(`/api/cards/${cardId}`, { method: 'DELETE' });
          await renderDeck(deckId);
          refreshStatsBar();
        } catch (err) {
          alert(err.message);
        }
      }
    });
  });
}

async function renderStudy(deckId) {
  appEl.innerHTML = `<p class='muted'>Loading study session…</p>`;
  const [decks, dueCards] = await Promise.all([
    api('/api/decks'),
    api(`/api/decks/${deckId}/due`),
  ]);
  const deck = decks.find((item) => item.id === deckId);
  if (!deck) throw new Error('Deck not found');

  let cards = dueCards.slice();
  let index = 0;
  let revealed = false;
  let busy = false;

  function draw() {
    if (index >= cards.length) {
      window.onkeydown = null;
      appEl.innerHTML = `
        <a href='#/deck/${deckId}' class='back-link'>← Back to deck</a>
        <section class='card done-card'>
          <h2>Done for today</h2>
          <p>You reviewed all due cards in <strong>${escapeHtml(deck.name)}</strong>.</p>
          <a class='button primary' href='#/deck/${deckId}'>Back to deck</a>
        </section>
      `;
      refreshStatsBar();
      return;
    }

    const card = cards[index];
    let html = `
      <a href='#/deck/${deckId}' class='back-link'>← Back to deck</a>
      <p class='study-progress'>Card ${index + 1} of ${cards.length}</p>
      <section class='card study-card'>
        <div class='card-side'>
          <div class='label'>Front</div>
          <div class='card-text'>${escapeHtml(card.front)}</div>
        </div>
    `;

    if (revealed) {
      html += `
        <hr>
        <div class='card-side'>
          <div class='label'>Back</div>
          <div class='card-text'>${escapeHtml(card.back)}</div>
        </div>
        <div class='grade-buttons'>
          <button class='grade again' data-grade='again'>Again <span class='key'>1</span></button>
          <button class='grade hard' data-grade='hard'>Hard <span class='key'>2</span></button>
          <button class='grade good' data-grade='good'>Good <span class='key'>3</span></button>
          <button class='grade easy' data-grade='easy'>Easy <span class='key'>4</span></button>
        </div>
      `;
    } else {
      html += `
        <button id='show-answer' class='button primary'>Show answer <span class='key'>Space</span></button>
      `;
    }

    html += `</section>`;
    appEl.innerHTML = html;

    if (revealed) {
      appEl.querySelectorAll('button[data-grade]').forEach((button) => {
        button.addEventListener('click', () => grade(button.dataset.grade));
      });
    } else {
      document.getElementById('show-answer').addEventListener('click', showAnswer);
    }
  }

  function showAnswer() {
    if (index >= cards.length || revealed) return;
    revealed = true;
    draw();
  }

  async function grade(value) {
    if (busy || !revealed || index >= cards.length) return;
    busy = true;
    const card = cards[index];
    try {
      await api(`/api/cards/${card.id}/review`, {
        method: 'POST',
        body: { grade: value },
      });
      index += 1;
      revealed = false;
      busy = false;
      draw();
      refreshStatsBar();
    } catch (err) {
      busy = false;
      alert(err.message);
    }
  }

  window.onkeydown = (event) => {
    if (event.code === 'Space' || event.key === ' ') {
      event.preventDefault();
      if (!revealed) showAnswer();
      return;
    }
    if (revealed && GRADE_KEYS[event.key]) {
      event.preventDefault();
      grade(GRADE_KEYS[event.key]);
    }
  };

  draw();
}

window.addEventListener('hashchange', render);
window.addEventListener('DOMContentLoaded', () => {
  if (!window.location.hash) {
    window.location.hash = '#/';
  }
  render();
});
