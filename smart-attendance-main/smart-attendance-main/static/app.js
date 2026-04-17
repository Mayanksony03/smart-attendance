// ── CUSTOM CURSOR ────────────────────────────────────────
(function () {
  const cursor   = document.querySelector('.cursor');
  const follower = document.querySelector('.cursor-follower');
  if (!cursor || !follower) return;

  let mx = 0, my = 0, fx = 0, fy = 0;

  document.addEventListener('mousemove', e => {
    mx = e.clientX; my = e.clientY;
    cursor.style.left   = mx + 'px';
    cursor.style.top    = my + 'px';
  });

  function animFollower() {
    fx += (mx - fx) * 0.12;
    fy += (my - fy) * 0.12;
    follower.style.left = fx + 'px';
    follower.style.top  = fy + 'px';
    requestAnimationFrame(animFollower);
  }
  animFollower();

  // Scale cursor on hover over clickable elements
  document.querySelectorAll('a, button, input, [role=button]').forEach(el => {
    el.addEventListener('mouseenter', () => {
      cursor.style.transform   = 'translate(-50%,-50%) scale(2.5)';
      cursor.style.background  = 'transparent';
      cursor.style.border      = '1px solid #cdff00';
      follower.style.transform = 'translate(-50%,-50%) scale(0.4)';
    });
    el.addEventListener('mouseleave', () => {
      cursor.style.transform   = 'translate(-50%,-50%) scale(1)';
      cursor.style.background  = '#cdff00';
      cursor.style.border      = 'none';
      follower.style.transform = 'translate(-50%,-50%) scale(1)';
    });
  });
})();

// ── UTILITY: show message ────────────────────────────────
function showMsg(text, type) {
  const el = document.getElementById('msg');
  if (!el) return;
  el.textContent = text;
  el.className = 'msg show ' + (type || 'info');
}

// ── STAGGER ANIMATION ON TABLE ROWS ─────────────────────
document.querySelectorAll('.data-table tbody tr').forEach((tr, i) => {
  tr.style.opacity = '0';
  tr.style.transform = 'translateY(12px)';
  tr.style.transition = `opacity 0.4s ${i * 0.05}s ease, transform 0.4s ${i * 0.05}s ease`;
  setTimeout(() => {
    tr.style.opacity = '1';
    tr.style.transform = 'translateY(0)';
  }, 100);
});
