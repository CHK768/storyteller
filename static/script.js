let isGenerating = false;
let totalPages = 0;
let imagesLoaded = 0;

function setTheme(theme) {
  document.getElementById('themeInput').value = theme;
  document.getElementById('themeInput').focus();
}

function setStatus(msg) {
  const bar = document.getElementById('statusBar');
  bar.classList.add('visible');
  document.getElementById('statusText').textContent = msg;
}

function hideStatus() {
  document.getElementById('statusBar').classList.remove('visible');
}

function setProgress(pct) {
  const wrap = document.getElementById('progressWrap');
  wrap.classList.add('visible');
  document.getElementById('progressBar').style.width = pct + '%';
}

function hideProgress() {
  document.getElementById('progressWrap').classList.remove('visible');
  document.getElementById('progressBar').style.width = '0%';
}

function showError(msg) {
  let el = document.getElementById('errorMsg');
  if (!el) {
    el = document.createElement('div');
    el.id = 'errorMsg';
    el.className = 'error-msg';
    document.querySelector('.input-section').insertAdjacentElement('afterend', el);
  }
  el.textContent = '❌ ' + msg;
  el.classList.add('visible');
}

function hideError() {
  const el = document.getElementById('errorMsg');
  if (el) el.classList.remove('visible');
}

function createPageCard(page, index) {
  const tpl = document.getElementById('pageTpl');
  const card = tpl.content.cloneNode(true);
  const div = card.querySelector('.story-page');
  div.dataset.index = index;
  div.querySelector('.page-num').textContent = `第 ${page.page_num} 页`;
  div.querySelector('.page-text').textContent = page.text;
  return div;
}

function updatePageImage(index, url) {
  const card = document.querySelector(`.story-page[data-index="${index}"]`);
  if (!card) return;

  const placeholder = card.querySelector('.image-placeholder');
  const img = card.querySelector('.page-image');

  if (!url) {
    placeholder.innerHTML = '<span style="font-size:2rem">🖼️</span><span>暂无插图</span>';
    return;
  }

  img.onload = () => {
    img.classList.add('loaded');
    placeholder.style.display = 'none';
  };
  img.onerror = () => {
    placeholder.innerHTML = '<span style="font-size:2rem">🖼️</span><span>图片加载失败</span>';
  };
  img.src = url;
}

function generateStory() {
  if (isGenerating) return;

  const theme = document.getElementById('themeInput').value.trim();
  if (!theme) {
    document.getElementById('themeInput').focus();
    document.getElementById('themeInput').style.borderColor = '#e74c3c';
    setTimeout(() => {
      document.getElementById('themeInput').style.borderColor = '';
    }, 1500);
    return;
  }

  // Reset
  isGenerating = true;
  totalPages = 0;
  imagesLoaded = 0;
  hideError();

  const btn = document.getElementById('generateBtn');
  btn.disabled = true;
  btn.querySelector('.btn-label').textContent = '创作中…';

  const storybook = document.getElementById('storybook');
  const pagesGrid = document.getElementById('pagesGrid');
  const bookCover = document.getElementById('bookCover');
  storybook.classList.remove('visible');
  bookCover.classList.remove('visible');
  pagesGrid.innerHTML = '';

  setStatus('✍️ 正在构思故事…');
  setProgress(5);

  const evtSource = new EventSource(`/generate?_=${Date.now()}`);

  // POST via fetch with SSE fallback — use POST + SSE approach
  // Actually Flask SSE with POST requires a workaround. Let's use GET with query param.
  // We POST the theme first to set it in session, then SSE.
  // Better: POST returns nothing, we use fetch to POST and handle streaming response.

  evtSource.close(); // Close the GET-based one

  const fetchController = new AbortController();

  fetch('/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme }),
    signal: fetchController.signal,
  }).then(response => {
    if (!response.ok) {
      return response.json().then(d => { throw new Error(d.error || '请求失败'); });
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    function pump() {
      return reader.read().then(({ done, value }) => {
        if (done) {
          finishGeneration();
          return;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const msg = JSON.parse(line.slice(6));
            handleMessage(msg);
          } catch (e) { /* ignore */ }
        }

        return pump();
      }).catch(err => {
        if (err.name !== 'AbortError') {
          showError(err.message);
          finishGeneration();
        }
      });
    }

    return pump();
  }).catch(err => {
    showError(err.message);
    finishGeneration();
  });

  function handleMessage(msg) {
    if (msg.type === 'status') {
      setStatus(msg.message);
    }

    else if (msg.type === 'story') {
      const story = msg.data;
      totalPages = story.pages.length;

      document.getElementById('bookTitle').textContent = story.title;
      bookCover.classList.add('visible');
      storybook.classList.add('visible');

      story.pages.forEach((page, i) => {
        const card = createPageCard(page, i);
        pagesGrid.appendChild(card);
      });

      setProgress(30);
    }

    else if (msg.type === 'image') {
      imagesLoaded++;
      updatePageImage(msg.page_index, msg.url);
      const pct = 30 + Math.round((imagesLoaded / Math.max(totalPages, 1)) * 68);
      setProgress(pct);
    }

    else if (msg.type === 'done') {
      finishGeneration();
    }

    else if (msg.type === 'error') {
      showError(msg.message);
      finishGeneration();
    }
  }

  function finishGeneration() {
    isGenerating = false;
    btn.disabled = false;
    btn.querySelector('.btn-label').textContent = '创作故事';
    hideStatus();
    setProgress(100);
    setTimeout(hideProgress, 800);
    if (totalPages > 0) {
      document.getElementById('pdfBar').style.display = 'block';
    }
  }
}

// Enter key support
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('themeInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') generateStory();
  });
});

function downloadPDF() {
  window.print();
}
