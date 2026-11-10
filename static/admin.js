// Επιβεβαίωση πριν από επικίνδυνες ενέργειες (δουλεύει με αυστηρό CSP, χωρίς inline handlers).
document.addEventListener("submit", (e) => {
  const message = e.target.dataset.confirm;
  if (message && !window.confirm(message)) e.preventDefault();
});
