// password-setup.js – lightweight UX for password creation

document.addEventListener('DOMContentLoaded', () => {
  const container = document.querySelector('.pw-setup-container');
  const form = container ? container.querySelector('form') : null;
  if (!form) return;

  form.addEventListener('submit', (e) => {
    const p1 = form.querySelector('input[name="new_password1"]');
    const p2 = form.querySelector('input[name="new_password2"]');
    if (p1 && p2 && p1.value !== p2.value) {
      e.preventDefault();
      container.classList.add('shake');
      setTimeout(() => container.classList.remove('shake'), 500);
    }
  });
});
