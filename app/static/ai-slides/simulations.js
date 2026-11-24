(() => {
  const kind = document.querySelector('main').dataset.simulation;
  const byId = id => document.getElementById(id);
  const output = byId('simulation-output');
  const canvas = byId('simulation-canvas');
  const context = canvas?.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let stopped = reduced;
  let elapsed = 0;
  let previous = 0;

  function drawOhm() {
    const voltage = Number(byId('voltage').value);
    const resistance = Number(byId('resistance').value);
    const current = resistance > 0 ? voltage / resistance : 0;
    context.clearRect(0, 0, 960, 380);
    context.strokeStyle = '#254973';
    context.lineWidth = 5;
    context.strokeRect(160, 100, 640, 180);
    context.fillStyle = '#fff';
    context.fillRect(410, 75, 140, 50);
    context.strokeRect(410, 75, 140, 50);
    context.fillStyle = '#16324f';
    context.font = '25px Arial';
    context.fillText('R = ' + resistance + ' Ω', 402, 55);
    context.fillText('U = ' + voltage + ' V', 150, 330);
    context.fillText('I = ' + current.toFixed(3) + ' A', 620, 330);
    context.beginPath();
    context.fillStyle = `rgba(255, 190, 40, ${Math.min(1, current / 3)})`;
    context.arc(480, 190, 34, 0, Math.PI * 2);
    context.fill(); context.stroke();
    output.textContent = `I = ${voltage} / ${resistance} = ${current.toFixed(3)} A`;
  }
  function drawPendulum() {
    const length = Number(byId('length').value);
    const amplitude = Number(byId('amplitude').value) * Math.PI / 180;
    const period = 2 * Math.PI * Math.sqrt(length / 9.81);
    const angle = amplitude * Math.cos(Math.sqrt(9.81 / length) * elapsed);
    const scale = 60 + length * 70;
    context.clearRect(0, 0, 960, 420);
    context.lineWidth = 4; context.strokeStyle = '#254973'; context.fillStyle = '#2563eb';
    context.beginPath(); context.moveTo(480, 50);
    const x = 480 + Math.sin(angle) * scale;
    const y = 50 + Math.cos(angle) * scale;
    context.lineTo(x, y); context.stroke();
    context.beginPath(); context.arc(x, y, 22, 0, Math.PI * 2); context.fill();
    output.textContent = `L = ${length} m · T ≈ ${period.toFixed(2)} s`;
  }
  if (kind === 'ohm') {
    document.querySelectorAll('input').forEach(input => input.addEventListener('input', drawOhm));
    drawOhm();
  } else if (kind === 'pendulum') {
    byId('pause').textContent = stopped ? 'Chạy chuyển động' : 'Dừng chuyển động';
    byId('pause').onclick = () => {
      stopped = !stopped;
      byId('pause').textContent = stopped ? 'Chạy chuyển động' : 'Dừng chuyển động';
    };
    function tick(timestamp) {
      if (!stopped && previous) elapsed += Math.min(0.05, (timestamp - previous) / 1000);
      previous = timestamp;
      drawPendulum();
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  } else {
    const regions = [
      ['Miền núi phía Bắc', 'Địa hình núi, có nhiều thung lũng và cao nguyên.', 104.1, 22.1],
      ['Đồng bằng sông Hồng', 'Đồng bằng được bồi tụ bởi hệ thống sông Hồng và sông Thái Bình.', 105.8, 20.8],
      ['Duyên hải miền Trung', 'Dải đồng bằng ven biển thường hẹp, phía tây có địa hình núi.', 108.2, 16],
      ['Tây Nguyên', 'Khu vực có các cao nguyên. Cần phân biệt cao nguyên với đồng bằng và địa giới hành chính.', 108, 13.5],
      ['Đồng bằng sông Cửu Long', 'Đồng bằng hạ lưu sông Mekong với hệ thống sông ngòi và kênh rạch.', 105.6, 10.1],
    ];
    const map = byId('geography-canvas');
    const draw = map.getContext('2d');
    let geometry;
    let selected = -1;
    let zoom = 1;
    const point = (lon, lat) => [480 + (lon - 106.1) * 43 * zoom, 310 - (lat - 16.4) * 38 * zoom];
    function paint() {
      draw.clearRect(0, 0, 960, 620);
      if (!geometry) return;
      draw.strokeStyle = '#326455'; draw.fillStyle = '#d5e7d7'; draw.lineWidth = 2;
      const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
      for (const polygon of polygons) {
        draw.beginPath();
        polygon[0].forEach(([lon, lat], index) => {
          const [x, y] = point(lon, lat);
          if (index === 0) draw.moveTo(x, y);
          else draw.lineTo(x, y);
        });
        draw.closePath(); draw.fill(); draw.stroke();
      }
      regions.forEach(([title, , lon, lat], index) => {
        const [x, y] = point(lon, lat);
        draw.beginPath(); draw.arc(x, y, index === selected ? 11 : 7, 0, Math.PI * 2);
        draw.fillStyle = index === selected ? '#bd5518' : '#245dd5'; draw.fill();
        draw.fillStyle = '#172d4a'; draw.font = '18px Arial'; draw.fillText(title, x + 15, y + 6);
      });
      if (byId('map-route-toggle').checked) {
        draw.save(); draw.strokeStyle = '#a83b16'; draw.lineWidth = 3; draw.setLineDash([10, 7]); draw.beginPath();
        regions.forEach(([, , lon, lat], index) => { const [x, y] = point(lon, lat); if (index === 0) draw.moveTo(x, y); else draw.lineTo(x, y); });
        draw.stroke(); draw.restore();
      }
    }
    function choose(index) {
      selected = index;
      byId('region-description').textContent = regions[index][1];
      paint();
    }
    const embedded = byId('offline-map-data');
    const geometryData = embedded ? Promise.resolve(JSON.parse(embedded.textContent)) : fetch('/static/ai-slides/vietnam.geojson').then(response => {
      if (!response.ok) throw new Error('map unavailable');
      return response.json();
    });
    geometryData.then(data => { geometry = data.geometry; paint(); }).catch(() => {
      byId('region-description').textContent = 'Chưa tải được dữ liệu bản đồ. Hãy thử tải lại trang.';
    });
    map.onclick = event => {
      const bounds = map.getBoundingClientRect();
      const x = (event.clientX - bounds.left) * map.width / bounds.width;
      const y = (event.clientY - bounds.top) * map.height / bounds.height;
      const index = regions.findIndex(([, , lon, lat]) => {
        const [px, py] = point(lon, lat);
        return Math.hypot(px - x, py - y) < 28;
      });
      if (index >= 0) choose(index);
    };
    byId('map-zoom-in').onclick = () => { zoom = Math.min(2, zoom + 0.2); paint(); };
    byId('map-zoom-out').onclick = () => { zoom = Math.max(0.6, zoom - 0.2); paint(); };
    byId('map-route-toggle').onchange = () => { byId('region-description').textContent = byId('map-route-toggle').checked ? 'Tuyến minh họa nối năm điểm vùng. Chọn từng vùng để so sánh địa hình; không dùng tuyến này để chỉ đường.' : 'Đã ẩn tuyến minh họa. Chọn một vùng để xem đặc điểm.'; paint(); };
    regions.forEach(([title], index) => {
      const button = document.createElement('button');
      button.textContent = title;
      button.onclick = () => choose(index);
      byId('map-regions').append(button);
    });
  }
  byId('reset').onclick = () => location.reload();
})();
