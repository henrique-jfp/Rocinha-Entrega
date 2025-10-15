(function(){
  const body = document.body;
  const routeId = Number(body.getAttribute('data-route-id'));
  const driverId = Number(body.getAttribute('data-driver-id'));
  const botUsername = body.getAttribute('data-bot-username') || 'SEU_BOT_USERNAME';
  const baseUrl = body.getAttribute('data-base-url') || '';

  // Initialize map
  const map = L.map('map', { zoomControl: true });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap'
  }).addTo(map);

  map.setView([-22.9, -43.2], 12);

  const markersLayer = L.layerGroup().addTo(map);
  const myLocationLayer = L.layerGroup().addTo(map);

  // Custom icon com número
  function createNumberedIcon(number, status){
    let bgColor = '#6366f1'; // pending
    if(status === 'delivered') bgColor = '#10b981';
    if(status === 'failed') bgColor = '#ef4444';
    
    const html = `<div style="
      width: 40px;
      height: 40px;
      border-radius: 50% 50% 50% 0;
      background: ${bgColor};
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 14px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      border: 3px solid #fff;
      transform: rotate(-45deg);
    "><span style="transform: rotate(45deg);">${number}</span></div>`;
    
    return L.divIcon({
      html: html,
      className: 'custom-pin',
      iconSize: [40, 40],
      iconAnchor: [20, 40],
      popupAnchor: [0, -40]
    });
  }

  function createPopupHtml(pkg){
    const nav = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
    const deliver = `tg://resolve?domain=${botUsername}&start=deliver_${pkg.id}`;
    const address = pkg.address || 'Sem endereço';
    const track = pkg.tracking_code || '';
    return `
      <div>
        <div class="popup-code">${track}</div>
        <div class="popup-addr">${address}</div>
        <div class="popup-actions">
          <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener">🧭 Navegar</a>
          <a class="popup-btn deliver" href="${deliver}">✓ Entregar</a>
        </div>
      </div>`;
  }

  function addPackageMarker(pkg, index){
    if(!(pkg.latitude && pkg.longitude)) return null;
    const icon = createNumberedIcon(index + 1, pkg.status);
    const marker = L.marker([pkg.latitude, pkg.longitude], { icon }).addTo(markersLayer);
    marker.bindPopup(createPopupHtml(pkg));
    marker.pkg = pkg;
    return marker;
  }

  function getStatusText(status){
    if(status === 'delivered') return 'Entregue';
    if(status === 'failed') return 'Falhou';
    return 'Pendente';
  }

  function createListItem(pkg, marker, index){
    const li = document.createElement('li');
    li.className = `list-item ${pkg.status}`;

    const pinNum = document.createElement('div');
    pinNum.className = 'pin-number';
    pinNum.textContent = index + 1;

    const info = document.createElement('div');
    info.className = 'pkg-info';

    const code = document.createElement('div');
    code.className = 'pkg-code';
    code.textContent = pkg.tracking_code || 'Sem código';

    const addr = document.createElement('div');
    addr.className = 'pkg-addr';
    addr.textContent = pkg.address || 'Sem endereço';

    info.appendChild(code);
    info.appendChild(addr);

    const badge = document.createElement('div');
    badge.className = 'status-badge';
    badge.textContent = getStatusText(pkg.status);

    const navBtn = document.createElement('a');
    navBtn.className = 'nav-btn';
    navBtn.textContent = '→';
    navBtn.title = 'Navegar';
    navBtn.href = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
    navBtn.target = '_blank';
    navBtn.rel = 'noopener';

    li.appendChild(pinNum);
    li.appendChild(info);
    li.appendChild(badge);
    li.appendChild(navBtn);

    li.addEventListener('click', (e)=>{
      if(e.target.tagName.toLowerCase() === 'a') return;
      if(marker){
        map.flyTo(marker.getLatLng(), 16, { duration: 0.5 });
        setTimeout(() => marker.openPopup(), 600);
      }
    });

    return li;
  }

  async function loadPackages(){
    const url = `${baseUrl}/route/${routeId}/packages`;
    try {
      const res = await fetch(url);
      if(!res.ok) throw new Error('Erro ao carregar');
      const data = await res.json();

      markersLayer.clearLayers();
      const list = document.getElementById('package-list');
      list.innerHTML = '';

      const group = [];
      let pending = 0, delivered = 0, failed = 0;

      data.forEach((pkg, index) => {
        const marker = addPackageMarker(pkg, index);
        if(marker) group.push(marker.getLatLng());
        list.appendChild(createListItem(pkg, marker, index));

        if(pkg.status === 'delivered') delivered++;
        else if(pkg.status === 'failed') failed++;
        else pending++;
      });

      // Update counter
      const counter = document.getElementById('counter');
      counter.textContent = `${data.length} pacote${data.length !== 1 ? 's' : ''} · ${pending} pendente${pending !== 1 ? 's' : ''} · ${delivered} entregue${delivered !== 1 ? 's' : ''}`;

      if(group.length){
        const bounds = L.latLngBounds(group);
        map.fitBounds(bounds.pad(0.1));
      }
    } catch(err){
      console.error('Erro:', err);
      document.getElementById('counter').textContent = 'Erro ao carregar pacotes';
    }
  }

  // Driver location
  let myMarker = null;
  function updateMyMarker(lat, lng){
    myLocationLayer.clearLayers();
    
    // Círculo azul com pulso
    const circle = L.circle([lat, lng], {
      radius: 30,
      color: '#2563eb',
      fillColor: '#3b82f6',
      fillOpacity: 0.3,
      weight: 2
    }).addTo(myLocationLayer);

    const dot = L.circleMarker([lat, lng], {
      radius: 8,
      color: '#fff',
      fillColor: '#2563eb',
      fillOpacity: 1,
      weight: 3
    }).addTo(myLocationLayer);

    myMarker = dot;
  }

  function postLocation(lat, lng){
    const url = `${baseUrl}/location/${driverId}`;
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latitude: lat, longitude: lng, timestamp: Date.now(), route_id: routeId })
    }).catch(()=>{});
  }

  if('geolocation' in navigator){
    navigator.geolocation.watchPosition((pos)=>{
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      updateMyMarker(lat, lng);
      postLocation(lat, lng);
    }, (err)=>{
      console.warn('Geolocation error', err);
    }, { enableHighAccuracy: true, maximumAge: 10_000, timeout: 10_000 });
  }

  // Initial load
  loadPackages();

  // Refresh every 2 min
  setInterval(loadPackages, 120_000);
})();
