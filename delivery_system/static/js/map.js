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

  // Armazena estado anterior para detectar mudanças
  let previousPackageStates = {};

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
    
    // Link de entrega - funciona tanto no Telegram quanto no navegador
    const deliverTelegram = `tg://resolve?domain=${botUsername}&start=deliver_${pkg.id}`;
    const deliverWeb = `https://t.me/${botUsername}?start=deliver_${pkg.id}`;
    
    const address = pkg.address || 'Sem endereço';
    const track = pkg.tracking_code || '';
    
    // Botão de contato desabilitado temporariamente (campo phone precisa migração)
    // let contactBtn = '';
    // if(pkg.phone){
    //   const phoneClean = pkg.phone.replace(/\D/g, ''); // Remove formatação
    //   const phoneFormatted = pkg.phone; // Mantém formatação original
    //   const whatsapp = `https://wa.me/55${phoneClean}`;
    //   contactBtn = `<a class="popup-btn contact" href="${whatsapp}" target="_blank" rel="noopener">📞 Contato</a>`;
    // }
    
    return `
      <div>
        <div class="popup-code">${track}</div>
        <div class="popup-addr">${address}</div>
        <div class="popup-actions">
          <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener">🧭 Navegar</a>
          <a class="popup-btn deliver" href="${deliverWeb}" target="_blank" rel="noopener">✓ Entregar</a>
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

  // Mostra notificação de atualização
  function showUpdateNotification(message, type = 'success'){
    const notification = document.createElement('div');
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: ${type === 'success' ? '#10b981' : '#3b82f6'};
      color: white;
      padding: 12px 20px;
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      font-weight: 600;
      z-index: 10000;
      animation: slideIn 0.3s ease-out;
    `;
    notification.textContent = message;
    
    // Adiciona animação
    const style = document.createElement('style');
    style.textContent = `
      @keyframes slideIn {
        from { transform: translateX(400px); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
      }
      @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(400px); opacity: 0; }
      }
    `;
    document.head.appendChild(style);
    
    document.body.appendChild(notification);
    
    // Remove após 3 segundos
    setTimeout(() => {
      notification.style.animation = 'slideOut 0.3s ease-out';
      setTimeout(() => notification.remove(), 300);
    }, 3000);
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
      let hasChanges = false;
      let changedPackages = [];

      data.forEach((pkg, index) => {
        const marker = addPackageMarker(pkg, index);
        if(marker) group.push(marker.getLatLng());
        list.appendChild(createListItem(pkg, marker, index));

        if(pkg.status === 'delivered') delivered++;
        else if(pkg.status === 'failed') failed++;
        else pending++;
        
        // Detecta mudanças de status
        const prevStatus = previousPackageStates[pkg.id];
        if(prevStatus && prevStatus !== pkg.status){
          hasChanges = true;
          changedPackages.push({
            tracking_code: pkg.tracking_code,
            from: prevStatus,
            to: pkg.status
          });
        }
        previousPackageStates[pkg.id] = pkg.status;
      });

      // Update counter
      const counter = document.getElementById('counter');
      counter.textContent = `${data.length} pacote${data.length !== 1 ? 's' : ''} · ${pending} pendente${pending !== 1 ? 's' : ''} · ${delivered} entregue${delivered !== 1 ? 's' : ''}`;

      if(group.length){
        const bounds = L.latLngBounds(group);
        map.fitBounds(bounds.pad(0.1));
      }
      
      // Mostra notificação se houver mudanças
      if(hasChanges){
        const deliveredCount = changedPackages.filter(p => p.to === 'delivered').length;
        const failedCount = changedPackages.filter(p => p.to === 'failed').length;
        
        let message = '✅ ';
        if(deliveredCount > 0){
          message += `${deliveredCount} pacote${deliveredCount > 1 ? 's' : ''} entregue${deliveredCount > 1 ? 's' : ''}`;
        }
        if(failedCount > 0){
          if(deliveredCount > 0) message += ', ';
          message += `${failedCount} falhou${failedCount > 1 ? '' : ''}`;
        }
        
        showUpdateNotification(message, 'success');
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

  // Refresh every 30 seconds (atualização rápida para feedback em tempo real)
  setInterval(loadPackages, 30_000);
})();
