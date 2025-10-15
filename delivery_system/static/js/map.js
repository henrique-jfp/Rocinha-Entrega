(function(){
  const body = document.body;
  const routeId = Number(body.getAttribute('data-route-id'));
  const driverId = Number(body.getAttribute('data-driver-id'));
  const botUsername = body.getAttribute('data-bot-username') || 'SEU_BOT_USERNAME';
  const baseUrl = body.getAttribute('data-base-url') || '';

  // Initialize map
  const map = L.map('map');
  const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  // Fit map to a default view (will adjust after data/geolocation)
  map.setView([-22.9, -43.2], 12);

  const markersLayer = L.layerGroup().addTo(map);
  const myLocationLayer = L.layerGroup().addTo(map);

  function createPopupHtml(pkg){
    const nav = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
    const deliver = `tg://resolve?domain=${botUsername}&start=deliver_${pkg.id}`;
    const address = pkg.address || '';
    const track = pkg.tracking_code || '';
    return `
      <div class="popup">
        <div><strong>${track}</strong></div>
        <div>${address}</div>
        <div class="actions">
          <a class="btn" href="${nav}" target="_blank" rel="noopener">Navegar</a>
          <a class="btn primary" href="${deliver}">Entregar</a>
        </div>
      </div>`;
  }

  function markerStyleByStatus(status){
    // Using circle markers for color differentiation
    if(status === 'delivered') return {radius: 10, color: '#2e7d32', fillColor: '#43a047', fillOpacity: 0.9};
    if(status === 'failed') return {radius: 10, color: '#b71c1c', fillColor: '#e53935', fillOpacity: 0.9};
    return {radius: 10, color: '#1565c0', fillColor: '#1e88e5', fillOpacity: 0.9};
  }

  function addPackageMarker(pkg){
    if(!(pkg.latitude && pkg.longitude)) return;
    const style = markerStyleByStatus(pkg.status);
    const marker = L.circleMarker([pkg.latitude, pkg.longitude], style).addTo(markersLayer);
    marker.bindPopup(createPopupHtml(pkg));
    marker.pkg = pkg;
    return marker;
  }

  function createListItem(pkg, marker){
    const li = document.createElement('li');
    li.className = `list-item ${pkg.status}`;

    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = pkg.tracking_code || '';

    const addr = document.createElement('div');
    addr.className = 'addr';
    addr.textContent = pkg.address || '';

    const actions = document.createElement('div');
    actions.className = 'actions';
    const nav = document.createElement('a');
    nav.className = 'btn';
    nav.textContent = 'Navegar';
    nav.href = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
    nav.target = '_blank';
    nav.rel = 'noopener';

    const deliver = document.createElement('a');
    deliver.className = 'btn primary';
    deliver.textContent = 'Entregar';
    deliver.href = `tg://resolve?domain=${botUsername}&start=deliver_${pkg.id}`;

    actions.appendChild(nav);
    actions.appendChild(deliver);

    li.appendChild(title);
    li.appendChild(addr);
    li.appendChild(actions);

    li.addEventListener('click', (e)=>{
      if(e.target.tagName.toLowerCase() === 'a') return; // don't pan when clicking buttons
      if(marker){
        map.panTo(marker.getLatLng());
        marker.openPopup();
      }
    });

    return li;
  }

  async function loadPackages(){
    const url = `${baseUrl}/route/${routeId}/packages`;
    const res = await fetch(url);
    if(!res.ok){
      console.error('Erro ao carregar pacotes');
      return;
    }
    const data = await res.json();

    markersLayer.clearLayers();
    const list = document.getElementById('package-list');
    list.innerHTML = '';

    const group = [];
    data.forEach(pkg => {
      const marker = addPackageMarker(pkg);
      if(marker){
        group.push(marker.getLatLng());
      }
      list.appendChild(createListItem(pkg, marker));
    });

    if(group.length){
      const bounds = L.latLngBounds(group);
      map.fitBounds(bounds.pad(0.2));
    }
  }

  // Geolocation and driver marker
  let myMarker = null;
  function updateMyMarker(lat, lng){
    myLocationLayer.clearLayers();
    const circle = L.circleMarker([lat, lng], {
      radius: 8,
      color: '#0d47a1',
      fillColor: '#2196f3',
      fillOpacity: 0.8
    });
    circle.addTo(myLocationLayer);
    myMarker = circle;
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
    }, (err)=>{
      console.warn('Geolocation error', err);
    }, { enableHighAccuracy: true, maximumAge: 10_000, timeout: 10_000 });

    // Send every 30s
    setInterval(()=>{
      if(!myMarker) return;
      const latlng = myMarker.getLatLng();
      postLocation(latlng.lat, latlng.lng);
    }, 30_000);
  }

  // Initial load
  loadPackages();

  // Optional: refresh package list every 2 minutes to see delivered status updates
  setInterval(loadPackages, 120_000);
})();
