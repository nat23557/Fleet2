// login.js – you can hook into inputs for extra flair later
document.addEventListener('DOMContentLoaded', () => {
  // e.g. shake on error:
  const form = document.querySelector('.login-container form');
  if (form && window.location.search.includes('error')) {
    form.classList.add('shake');
    setTimeout(() => form.classList.remove('shake'), 500);
  }
});
