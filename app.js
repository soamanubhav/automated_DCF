const revenueCtx = document.getElementById('revenueChart');
const fcffCtx = document.getElementById('fcffChart');

new Chart(revenueCtx, {
  type: 'bar',
  data: {
    labels: ['2023', '2024', '2025', '2026', '2027'],
    datasets: [{
      label: 'Revenue',
      data: [900, 1150, 1400, 1650, 1900],
      backgroundColor: '#2b82f6'
    }]
  },
  options: {
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      y: { beginAtZero: true, ticks: { color: '#374151' }, grid: { color: '#d7dde7' } },
      x: { ticks: { color: '#374151' }, grid: { display: false } }
    }
  }
});

new Chart(fcffCtx, {
  type: 'line',
  data: {
    labels: ['2023', '2024', '2025', '2026', '2027'],
    datasets: [{
      label: 'FCFF',
      data: [850, 1000, 1180, 1450, 1820],
      borderColor: '#e2772b',
      backgroundColor: '#e2772b',
      tension: 0.3,
      fill: false
    }]
  },
  options: {
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      y: { beginAtZero: true, ticks: { color: '#374151' }, grid: { color: '#d7dde7' } },
      x: { ticks: { color: '#374151' }, grid: { display: false } }
    }
  }
});

const sliderGroups = document.querySelectorAll('.slider-group');
sliderGroups.forEach((group) => {
  const input = group.querySelector('input[type="range"]');
  const valueEl = group.querySelector('span');
  input.addEventListener('input', () => {
    valueEl.textContent = Number(input.value).toFixed(1);
  });
});
