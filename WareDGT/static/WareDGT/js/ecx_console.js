function getCsrfToken() {
  const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return el ? el.value : '';
}

function showToast(message, level = 'success') {
  if (typeof window.showMessage === 'function') {
    window.showMessage(level, message);
  } else {
    alert(message);
  }
}

async function submitLoad({ warehouseId, stocklineId, qty, truckPlate, selectedSymbol, selectedGrade }) {
  const payload = {
    warehouse_id: warehouseId,
    stockline_id: stocklineId,
    quantity: Number(qty),
    truck_plate: (truckPlate || '').trim(),
    symbol: selectedSymbol,
  };
  // Only include grade if the user selected one. Leaving it out allows
  // multiple grades of the same seed type to be loaded in a single request.
  if (selectedGrade != null && selectedGrade !== '') {
    payload.grade = selectedGrade;
  }

  const res = await fetch(`/api/warehouses/${warehouseId}/load/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
      'ngrok-skip-browser-warning': '1',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    let body = {};
    try { body = await res.json(); } catch {}
    showToast(`Load failed: ${res.status} ${(body.detail || JSON.stringify(body))}`, 'error');
    throw new Error(`Load failed: ${res.status}`);
  }

  const data = await res.json();
  showToast('Load submitted (PENDING approval).');
  return data;
}

// Optional helper to manage form state if a standard form is present
function setupLoadForm() {
  const warehouseSel = document.getElementById('warehouse');
  const stocklineSel = document.getElementById('stockline');
  const qtyInput = document.getElementById('qty');
  const symbolSel = document.getElementById('symbol');
  const gradeSel = document.getElementById('grade');
  const plateInput = document.getElementById('truck_plate');
  const submitBtn = document.getElementById('submit-load');
  const form = document.getElementById('load-form');

  function updateDisabled() {
    const warehouseId = warehouseSel && warehouseSel.value;
    const stocklineId = stocklineSel && stocklineSel.value;
    const qty = qtyInput && qtyInput.value;
    const selectedSymbol = symbolSel && symbolSel.value;
    // Grade is optional; do not disable submit when it's blank.
    if (submitBtn) {
      submitBtn.disabled = !warehouseId || !stocklineId || !qty || !selectedSymbol;
    }
  }

  [warehouseSel, stocklineSel, qtyInput, symbolSel, gradeSel].forEach(el => {
    if (el) el.addEventListener('change', updateDisabled);
  });
  if (qtyInput) qtyInput.addEventListener('input', updateDisabled);
  updateDisabled();

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await submitLoad({
          warehouseId: warehouseSel ? warehouseSel.value : '',
          stocklineId: stocklineSel ? stocklineSel.value : '',
          qty: qtyInput ? qtyInput.value : '',
          truckPlate: plateInput ? plateInput.value : '',
          selectedSymbol: symbolSel ? symbolSel.value : '',
          selectedGrade: gradeSel ? gradeSel.value : null,
        });
        form.reset();
        updateDisabled();
      } catch (err) {
        // don't reset form on error
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('load-form')) {
    setupLoadForm();
  }
});

window.submitLoad = submitLoad;
window.setupLoadForm = setupLoadForm;

