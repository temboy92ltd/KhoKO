document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', e => { if (!confirm(form.dataset.confirm)) e.preventDefault(); });
});
const existing = document.getElementById('existing-product');
if (existing) existing.addEventListener('change', () => {
  const option = existing.selectedOptions[0];
  for (const field of ['name', 'color', 'vehicle']) document.getElementById(`product-${field}`).value = option.dataset[field] || '';
});
const dialog = document.getElementById('export-dialog');
if (dialog) {
  document.querySelectorAll('.select-product').forEach(button => button.addEventListener('click', () => {
    document.getElementById('selected-id').value = button.dataset.id;
    document.getElementById('selected-label').textContent = button.dataset.label;
    document.getElementById('selected-stock').textContent = Number(button.dataset.stock).toLocaleString('vi-VN');
    const quantity = document.getElementById('export-quantity');
    quantity.max = button.dataset.stock;
    quantity.value = '1';
    dialog.showModal();
    quantity.focus();
  }));
  document.getElementById('close-dialog').addEventListener('click', () => dialog.close());
}
document.querySelectorAll('.stock-form, #export-form').forEach(form => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"], button:not([type])');
    if (button) { button.disabled = true; button.textContent = 'Đang ghi nhận...'; }
  });
});
