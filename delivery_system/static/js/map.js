(function(){
  try {
    console.log('🚀 Map script iniciado');
    
    const body = document.body;
    const routeId = Number(body.getAttribute('data-route-id'));
    const driverId = Number(body.getAttribute('data-driver-id'));
    const botUsername = body.getAttribute('data-bot-username') || 'SEU_BOT_USERNAME';
    const baseUrl = body.getAttribute('data-base-url') || '';
    
    console.log('📍 Variáveis carregadas:', { routeId, driverId, botUsername, baseUrl });

    // Initialize map - estilo Google Maps (colorido e claro)
    const map = L.map('map', {
      center: [-22.9, -43.2],
      zoom: 13,
      zoomControl: true,
      preferCanvas: true
    });
    
    console.log('✅ Mapa Leaflet inicializado');
    
    // Mapa estilo Google Maps - cores vibrantes e saturadas
    L.tileLayer('https://mt1.google.com/vt/lyrs=r&x={x}&y={y}&z={z}', {
      maxZoom: 20,
      attribution: '© Google Maps',
      subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
    }).addTo(map);
    
    // Alternativa: OpenStreetMap padrão - descomente para usar
    // L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    //   maxZoom: 19,
    //   attribution: '© CARTO © OpenStreetMap',
    //   subdomains: 'abcd'
    // }).addTo(map);

    const markersLayer = L.layerGroup().addTo(map);
    const myLocationLayer = L.layerGroup().addTo(map);

    // Armazena estado anterior para detectar mudanças
    let previousPackageStates = {};

  // Função para calcular distância entre dois pontos (em metros)
  function getDistance(lat1, lng1, lat2, lng2) {
    const R = 6371e3; // Raio da Terra em metros
    const φ1 = lat1 * Math.PI / 180;
    const φ2 = lat2 * Math.PI / 180;
    const Δφ = (lat2 - lat1) * Math.PI / 180;
    const Δλ = (lng2 - lng1) * Math.PI / 180;

    const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
              Math.cos(φ1) * Math.cos(φ2) *
              Math.sin(Δλ/2) * Math.sin(Δλ/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

    return R * c; // Distância em metros
  }

  // Normaliza o endereço em uma chave: "rua + número" (ignora complemento)
  // ============================================
  // 🎨 SISTEMA DE CORES POR ÁREA GEOGRÁFICA
  // ============================================
  
  // Define cores vibrantes para diferentes áreas
  const AREA_COLORS = [
    { primary: '#9333ea', shadow: 'rgba(147, 51, 234, 0.4)', name: 'Roxo' },      // Área 1
    { primary: '#ec4899', shadow: 'rgba(236, 72, 153, 0.4)', name: 'Rosa' },      // Área 2
    { primary: '#f59e0b', shadow: 'rgba(245, 158, 11, 0.4)', name: 'Laranja' },   // Área 3
    { primary: '#10b981', shadow: 'rgba(16, 185, 129, 0.4)', name: 'Verde' },     // Área 4
    { primary: '#3b82f6', shadow: 'rgba(59, 130, 246, 0.4)', name: 'Azul' },      // Área 5
    { primary: '#ef4444', shadow: 'rgba(239, 68, 68, 0.4)', name: 'Vermelho' },   // Área 6
    { primary: '#8b5cf6', shadow: 'rgba(139, 92, 246, 0.4)', name: 'Violeta' },   // Área 7
    { primary: '#06b6d4', shadow: 'rgba(6, 182, 212, 0.4)', name: 'Ciano' },      // Área 8
  ];

  // Divide pacotes em áreas geográficas usando K-means simplificado
  function divideIntoAreas(packages) {
    if (packages.length === 0) return [];
    
    // Filtra pacotes com coordenadas válidas
    const validPackages = packages.filter(p => p.latitude && p.longitude);
    if (validPackages.length === 0) return [];
    
    // Determina número de áreas (máximo 8, mínimo 2)
    const numAreas = Math.min(8, Math.max(2, Math.ceil(validPackages.length / 10)));
    
    // Inicializa centroides aleatórios
    const centroids = [];
    const step = Math.floor(validPackages.length / numAreas);
    for (let i = 0; i < numAreas; i++) {
      const pkg = validPackages[i * step] || validPackages[0];
      centroids.push({ lat: pkg.latitude, lng: pkg.longitude });
    }
    
    // Itera para ajustar centroides (K-means simplificado - 5 iterações)
    for (let iter = 0; iter < 5; iter++) {
      const clusters = Array.from({ length: numAreas }, () => []);
      
      // Atribui cada pacote ao centroide mais próximo
      validPackages.forEach(pkg => {
        let minDist = Infinity;
        let bestCluster = 0;
        
        centroids.forEach((centroid, idx) => {
          const dist = Math.sqrt(
            Math.pow(pkg.latitude - centroid.lat, 2) + 
            Math.pow(pkg.longitude - centroid.lng, 2)
          );
          if (dist < minDist) {
            minDist = dist;
            bestCluster = idx;
          }
        });
        
        clusters[bestCluster].push(pkg);
      });
      
      // Recalcula centroides
      clusters.forEach((cluster, idx) => {
        if (cluster.length > 0) {
          const avgLat = cluster.reduce((sum, p) => sum + p.latitude, 0) / cluster.length;
          const avgLng = cluster.reduce((sum, p) => sum + p.longitude, 0) / cluster.length;
          centroids[idx] = { lat: avgLat, lng: avgLng };
        }
      });
    }
    
    // Atribui cor de área para cada pacote
    validPackages.forEach(pkg => {
      let minDist = Infinity;
      let areaIndex = 0;
      
      centroids.forEach((centroid, idx) => {
        const dist = Math.sqrt(
          Math.pow(pkg.latitude - centroid.lat, 2) + 
          Math.pow(pkg.longitude - centroid.lng, 2)
        );
        if (dist < minDist) {
          minDist = dist;
          areaIndex = idx;
        }
      });
      
      pkg.areaColor = AREA_COLORS[areaIndex];
      pkg.areaIndex = areaIndex + 1;
    });
    
    return validPackages;
  }

  function normalizeAddressKey(address) {
    if (!address) return null;
    let a = (address + '').toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '');
    // captura número principal (primeira sequência de dígitos)
    const numMatch = a.match(/(\d{1,6})/);
    if (!numMatch) return null;
    const number = numMatch[1];
    // parte da rua antes do número (ou até a vírgula)
    const beforeNum = a.split(number)[0] || a.split(',')[0] || a;
    const street = beforeNum.replace(/[^a-z\s]/g, ' ').replace(/\s+/g, ' ').trim();
    if (!street || !number) return null;
    return `${street} ${number}`;
  }

  // Agrupa pacotes por endereço (mesmo número); fallback: itens sem endereço ficam sozinhos
  function clusterPackages(packages) {
    const groups = new Map();
    const singles = [];
    for (const pkg of packages) {
      const key = normalizeAddressKey(pkg.address);
      if (!key || !pkg.latitude || !pkg.longitude) {
        singles.push(pkg);
        continue;
      }
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(pkg);
    }

    const clusters = [];
    // Converte grupos em clusters
    for (const [key, list] of groups.entries()) {
      const lat = list[0].latitude;
      const lng = list[0].longitude;
      clusters.push({ packages: list, lat, lng, key });
    }
    // Cada single vira um cluster próprio
    for (const p of singles) {
      clusters.push({ packages: [p], lat: p.latitude, lng: p.longitude, key: null });
    }
    return clusters;
  }

  // Pins estilo SPX Motorista - Gota/Lágrima com cores por área
  function createNumberedIcon(number, status, isCluster = false, areaColor = null){
    // Se não tiver cor de área, usa cor por status
    let pinColor = areaColor ? areaColor.primary : '#9333ea';
    let shadowColor = areaColor ? areaColor.shadow : 'rgba(147, 51, 234, 0.4)';
    
    // Sobrescreve com cor de status se entregue/falhou
    if(status === 'delivered') {
      pinColor = '#10b981';
      shadowColor = 'rgba(16, 185, 129, 0.4)';
    }
    if(status === 'failed') {
      pinColor = '#ef4444';
      shadowColor = 'rgba(239, 68, 68, 0.4)';
    }
    
    // Cluster - múltiplos pacotes
    if (isCluster) {
      const html = `
      <div style="position: relative; width: 40px; height: 52px;">
        <!-- Pin em formato de gota/lágrima estilo SPX -->
        <div style="
          width: 40px;
          height: 40px;
          background: ${pinColor};
          border-radius: 50% 50% 50% 0;
          transform: rotate(-45deg);
          position: absolute;
          top: 0;
          left: 0;
          box-shadow: 0 3px 10px ${shadowColor};
          border: 3px solid #fff;
        "></div>
        
        <!-- Número dentro do pin -->
        <div style="
          position: absolute;
          top: 8px;
          left: 8px;
          width: 24px;
          height: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          font-weight: 800;
          font-size: 14px;
          font-family: 'Inter', sans-serif;
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
          z-index: 1;
        ">${number}</div>
        
        <!-- Badge de cluster -->
        <div style="
          position: absolute;
          top: -6px;
          right: -6px;
          background: #fff;
          color: ${pinColor};
          min-width: 18px;
          height: 18px;
          border-radius: 9px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 10px;
          font-weight: 800;
          padding: 0 4px;
          border: 2px solid ${pinColor};
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
          z-index: 2;
        ">+</div>
      </div>`;
      
      return L.divIcon({
        html: html,
        className: '',
        iconSize: [40, 52],
        iconAnchor: [20, 50]
      });
    }
    
    // Pin individual - gota/lágrima estilo SPX
    const html = `
    <div style="position: relative; width: 36px; height: 48px;">
      <!-- Pin em formato de gota/lágrima -->
      <div style="
        width: 36px;
        height: 36px;
        background: ${pinColor};
        border-radius: 50% 50% 50% 0;
        transform: rotate(-45deg);
        position: absolute;
        top: 0;
        left: 0;
        box-shadow: 0 3px 10px ${shadowColor};
        border: 3px solid #fff;
      "></div>
      
      <!-- Número dentro -->
      <div style="
        position: absolute;
        top: 6px;
        left: 6px;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #fff;
        font-weight: 800;
        font-size: 13px;
        font-family: 'Inter', sans-serif;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
        z-index: 1;
      ">${number}</div>
    </div>`;
    
    return L.divIcon({
      html: html,
      className: '',
      iconSize: [36, 48],
      iconAnchor: [18, 46]
    });
  }

  function createPopupHtml(pkg){
    const nav = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
    
    // Link de entrega via comando /entrega dedicado
    const deliverWeb = `https://t.me/${botUsername}?start=entrega_deliver_${pkg.id}`;
    
    const address = pkg.address || 'Sem endereço';
    const track = pkg.tracking_code || '';
    
    return `
      <div>
        <div class="popup-code">${track}</div>
        <div class="popup-addr">${address}</div>
        <div style="
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px solid #e5e7eb;
          display: flex;
          gap: 6px;
          flex-direction: column;
        ">
          <div style="display: flex; gap: 6px;">
            <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener" style="flex: 1; text-align: center;">🧭 Navegar</a>
            <a class="popup-btn deliver" href="${deliverWeb}" target="_blank" rel="noopener" style="flex: 1; text-align: center;">✓ Entregar</a>
          </div>
          ${pkg.status === 'pending' ? `
            <button onclick="markPackageDelivered(${pkg.id})" style="
              padding: 8px 12px;
              background: #10b981;
              color: white;
              border: none;
              border-radius: 6px;
              font-weight: 600;
              font-size: 13px;
              cursor: pointer;
              transition: all 0.2s;
              width: 100%;
            " onmouseover="this.style.background='#059669'" onmouseout="this.style.background='#10b981'">
              ✅ Marcar Entregue (Rápido)
            </button>
          ` : ''}
        </div>
      </div>`;
  }

  // Popup para cluster com múltiplos pacotes
  function createClusterPopupHtml(packages){
    const firstPkg = packages[0];
    const nav = `https://www.google.com/maps?q=${firstPkg.latitude},${firstPkg.longitude}`;
    
    const getStatusEmoji = (status) => {
      if(status === 'delivered') return '✅';
      if(status === 'failed') return '❌';
      return '📦';
    };
    
    const getStatusText = (status) => {
      if(status === 'delivered') return 'Entregue';
      if(status === 'failed') return 'Falhou';
      return 'Pendente';
    };
    
    const packagesList = packages.map(pkg => {
      const deliverWeb = `https://t.me/${botUsername}?start=entrega_deliver_${pkg.id}`;
      const emoji = getStatusEmoji(pkg.status);
      const statusText = getStatusText(pkg.status);
      const addr = (pkg.address || 'Sem endereço').substring(0, 50);
      
      return `
        <div style="
          padding: 8px;
          margin: 4px 0;
          background: ${pkg.status === 'delivered' ? '#f0fdf4' : pkg.status === 'failed' ? '#fef2f2' : '#f8fafc'};
          border-radius: 6px;
          border-left: 3px solid ${pkg.status === 'delivered' ? '#10b981' : pkg.status === 'failed' ? '#ef4444' : '#6366f1'};
        ">
          <div style="font-weight: 600; font-size: 13px; margin-bottom: 2px;">
            ${emoji} ${pkg.tracking_code || 'Sem código'}
          </div>
          <div style="font-size: 11px; color: #64748b; margin-bottom: 4px;">
            ${addr}${addr.length >= 50 ? '...' : ''}
          </div>
          <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
            <span style="font-size: 10px; color: #94a3b8; font-weight: 600;">${statusText}</span>
            ${pkg.status === 'pending' ? `
              <button onclick="markPackageDelivered(${pkg.id}); event.stopPropagation();" style="
                font-size: 10px;
                padding: 2px 6px;
                background: #10b981;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.2s;
              " onmouseover="this.style.background='#059669'" onmouseout="this.style.background='#10b981'">✅ Marcar</button>
              <a href="${deliverWeb}" target="_blank" rel="noopener" style="
                font-size: 10px;
                padding: 2px 6px;
                background: #3b82f6;
                color: white;
                border-radius: 4px;
                text-decoration: none;
                font-weight: 600;
              " title="Abre Telegram para entrega completa com fotos">Telegram</a>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');

    // Link para entregar todos com token curto (evita limite de 64 chars do Telegram)
    const pendingIds = packages.filter(p => p.status === 'pending').map(p => p.id);
    let groupLink = null;
    if (pendingIds.length > 0) {
      // criamos o link sob demanda via token (evita expor IDs longos)
      // usamos um placeholder e substituímos após gerar o token
      groupLink = `javascript:void(0)`;
    }
    
    return `
      <div style="min-width: 280px; max-width: 320px;">
        <div style="
          background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
          color: white;
          padding: 12px;
          margin: -12px -12px 12px -12px;
          border-radius: 8px 8px 0 0;
          font-weight: 700;
          font-size: 14px;
        ">
          📍 ${packages.length} Pacote${packages.length > 1 ? 's' : ''} nesta Parada
        </div>
        <div style="max-height: 300px; overflow-y: auto;">
          ${packagesList}
        </div>
        <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid #e2e8f0; display: flex; gap: 8px; flex-direction: column;">
          <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener" style="width: 100%; text-align: center;">
            🧭 Navegar para este Endereço
          </a>
          ${pendingIds.length > 0 ? `
          <a class="popup-btn deliver deliver-all" href="#" data-ids="${pendingIds.join(',')}" style="
            width: 100%; text-align: center; background: #10b981; color: white; font-size: 14px; padding: 10px; border: 1px solid #059669; border-radius: 10px; font-weight: 800;
          ">
            ✓ Entregar todos deste endereço
          </a>` : ''}
        </div>
      </div>
    `;
  }

  // Adiciona marcador individual
  function addPackageMarker(pkg, index){
    if(!(pkg.latitude && pkg.longitude)) return null;
    const icon = createNumberedIcon(index + 1, pkg.status, false, pkg.areaColor);
    const marker = L.marker([pkg.latitude, pkg.longitude], { icon }).addTo(markersLayer);
    marker.bindPopup(createPopupHtml(pkg));
    marker.pkg = pkg;
    return marker;
  }

  // Adiciona marcador de cluster
  function addClusterMarker(cluster, clusterIndex){
    const packages = cluster.packages;
    const count = packages.length;
    
    // Determina status dominante do cluster
    const statuses = packages.map(p => p.status);
    let dominantStatus = 'pending';
    if(statuses.every(s => s === 'delivered')) dominantStatus = 'delivered';
    else if(statuses.every(s => s === 'failed')) dominantStatus = 'failed';
    
    // Usa cor do primeiro pacote do cluster
    const areaColor = packages[0].areaColor || null;
    
    const icon = createNumberedIcon(clusterIndex + 1, dominantStatus, true, areaColor);
    const marker = L.marker([cluster.lat, cluster.lng], { icon }).addTo(markersLayer);
    marker.bindPopup(createClusterPopupHtml(packages), { maxWidth: 340 });
    marker.cluster = cluster;
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

    // Indicador de cor de área
    if (pkg.areaColor && pkg.status === 'pending') {
      const areaIndicator = document.createElement('div');
      areaIndicator.className = 'area-indicator';
      areaIndicator.style.cssText = `
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        background: ${pkg.areaColor.primary};
        border-radius: 0 4px 4px 0;
      `;
      li.appendChild(areaIndicator);
      li.style.position = 'relative';
    }

    const pinNum = document.createElement('div');
    pinNum.className = 'pin-number';
    pinNum.textContent = index + 1;
    
    // Aplica cor de área ao número se pendente
    if (pkg.areaColor && pkg.status === 'pending') {
      pinNum.style.background = pkg.areaColor.primary;
    }

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

    // Botão de ação (Marcar Entregue ou Navegar)
    const actionBtn = document.createElement('button');
    actionBtn.className = 'action-btn';
    actionBtn.style.cssText = `
      padding: 6px 12px;
      margin-left: 8px;
      border: none;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.2s ease;
    `;
    
    if (pkg.status === 'pending') {
      actionBtn.textContent = '✅ Marcar Entregue';
      actionBtn.style.background = '#10b981';
      actionBtn.style.color = 'white';
      actionBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await markPackageDelivered(pkg.id);
      });
    } else if (pkg.status === 'delivered') {
      actionBtn.textContent = '✔️ Entregue';
      actionBtn.style.background = '#d1d5db';
      actionBtn.style.color = '#666';
      actionBtn.disabled = true;
    } else if (pkg.status === 'failed') {
      actionBtn.textContent = '❌ Falhou';
      actionBtn.style.background = '#ef4444';
      actionBtn.style.color = 'white';
      actionBtn.disabled = true;
    }

    const navBtn = document.createElement('a');
    navBtn.className = 'nav-btn';
    navBtn.textContent = '🗺️';
    navBtn.title = 'Navegar no Google Maps';
    navBtn.href = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
    navBtn.target = '_blank';
    navBtn.rel = 'noopener';
    navBtn.style.cssText = `
      padding: 6px 10px;
      margin-left: 4px;
      text-decoration: none;
      display: inline-block;
    `;

    // Botão de Entregar via Telegram (fluxo completo com fotos)
    let deliverBtn = null;
    if (pkg.status === 'pending') {
      deliverBtn = document.createElement('a');
      deliverBtn.className = 'deliver-btn';
      deliverBtn.textContent = '📋 Entregar';
      deliverBtn.title = 'Abrir Telegram para registro completo com fotos';
      deliverBtn.href = `https://t.me/${botUsername}?start=entrega_deliver_${pkg.id}`;
      deliverBtn.target = '_blank';
      deliverBtn.rel = 'noopener';
      deliverBtn.style.cssText = `
        padding: 6px 10px;
        margin-left: 4px;
        text-decoration: none;
        display: inline-block;
        background: #3b82f6;
        color: white;
        border-radius: 4px;
        font-size: 12px;
        font-weight: 600;
      `;
    }

    li.appendChild(pinNum);
    li.appendChild(info);
    li.appendChild(badge);
    li.appendChild(actionBtn);
    li.appendChild(navBtn);
    if (deliverBtn) li.appendChild(deliverBtn);

    li.addEventListener('click', (e)=>{
      if(e.target.tagName.toLowerCase() === 'a' || e.target.tagName.toLowerCase() === 'button') return;
      if(marker){
        map.flyTo(marker.getLatLng(), 16, { duration: 0.5 });
        setTimeout(() => marker.openPopup(), 600);
      }
    });

    return li;
  }

  // Função para marcar pacote como entregue
  async function markPackageDelivered(packageId) {
    try {
      console.log(`📦 Marcando pacote ${packageId} como entregue...`);
      
      const response = await fetch(`${baseUrl}/package/${packageId}/mark-delivered`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'delivered' })
      });
      
      if (!response.ok) {
        const error = await response.text();
        throw new Error(`Erro ${response.status}: ${error}`);
      }
      
      const result = await response.json();
      console.log('✅ Pacote marcado como entregue:', result);
      
      showUpdateNotification('✅ Entrega registrada com sucesso!', 'success');
      
      // Recarrega pacotes para atualizar UI
      setTimeout(() => loadPackages(), 500);
      
    } catch (err) {
      console.error('❌ Erro ao marcar entrega:', err);
      showUpdateNotification(`❌ Erro: ${err.message}`, 'error');
    }
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
    console.log('🔍 Carregando pacotes de:', url);
    console.log('📦 RouteID:', routeId, 'DriverID:', driverId, 'BaseURL:', baseUrl);
    
    try {
      const res = await fetch(url);
      console.log('📡 Response status:', res.status, res.statusText);
      
      if(!res.ok) {
        const errorText = await res.text();
        console.error('❌ Erro HTTP:', res.status, errorText);
        throw new Error(`Erro ${res.status}: ${errorText}`);
      }
      
      let data;
      try {
        data = await res.json();
      } catch(jsonErr) {
        const text = await res.text();
        console.error('❌ Erro ao fazer parse JSON:', jsonErr);
        console.error('📝 Response text:', text.substring(0, 500));
        throw new Error(`JSON inválido: ${jsonErr.message}`);
      }
      
      console.log('✅ Dados recebidos:', data.length, 'pacotes', data);
      
      if (!Array.isArray(data)) {
        console.error('❌ Dados não são um array:', typeof data);
        throw new Error(`Tipo inesperado: esperado array, recebido ${typeof data}`);
      }

      markersLayer.clearLayers();
      const list = document.getElementById('package-list');
      list.innerHTML = '';

      const group = [];
      let pending = 0, delivered = 0, failed = 0;
      let hasChanges = false;
      let changedPackages = [];

      // 🎨 DIVIDE PACOTES EM ÁREAS GEOGRÁFICAS COM CORES
      divideIntoAreas(data);
      console.log('🎨 Áreas coloridas atribuídas aos pacotes');

      // Agrupa pacotes próximos
      const clusters = clusterPackages(data);
      console.log('🗂️ Clusters criados:', clusters.length);
      let displayIndex = 0; // número da parada (cluster)

      clusters.forEach((cluster) => {
        if(cluster.packages.length === 1){
          // Parada com 1 pacote
          const pkg = cluster.packages[0];
          const marker = addPackageMarker(pkg, displayIndex);
          if(marker) group.push(marker.getLatLng());
          list.appendChild(createListItem(pkg, marker, displayIndex));
          displayIndex++;
        } else {
          // Parada com múltiplos pacotes no mesmo endereço
          const marker = addClusterMarker(cluster, displayIndex);
          if(marker) group.push(marker.getLatLng());
          // Todos os itens listados recebem o mesmo número de parada
          cluster.packages.forEach((pkg) => {
            list.appendChild(createListItem(pkg, marker, displayIndex));
          });
          displayIndex++;
        }
        
        // Conta estatísticas e detecta mudanças
        cluster.packages.forEach((pkg) => {
          if(pkg.status === 'delivered') delivered++;
          else if(pkg.status === 'failed') failed++;
          else pending++;
          
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
      
      console.log('✅ Pacotes carregados com sucesso!');
    } catch(err){
      console.error('❌ Erro completo:', err);
      console.error('❌ Stack:', err.stack);
      document.getElementById('counter').textContent = `Erro ao carregar pacotes: ${err.message}`;
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

  // Delegação de evento: clicar em "Entregar todos deste endereço"
  document.addEventListener('click', async (e) => {
    const a = e.target.closest('a.deliver-all');
    if (!a) return;
    e.preventDefault();
    try {
      const ids = (a.getAttribute('data-ids') || '').split(',').map(x => Number(x)).filter(Boolean);
      if (!ids.length) return;
      console.log('🚀 Criando token para IDs:', ids);
      // Cria token curto no backend
      const res = await fetch(`${baseUrl}/group-token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ package_ids: ids })
      });
      console.log('📡 Resposta do /group-token:', res.status, res.statusText);
      if (!res.ok) {
        const errorText = await res.text();
        console.error('❌ Erro no /group-token:', errorText);
        throw new Error('Falha ao gerar token');
      }
      const { token } = await res.json();
      console.log('✅ Token criado:', token);
      // Monta deep link curto usando comando /entrega
      const link = `https://t.me/${botUsername}?start=entrega_deliverg_${encodeURIComponent(token)}`;
      console.log('🔗 Link gerado:', link);
      // Abre o Telegram
      window.open(link, '_blank', 'noopener');
    } catch (err) {
      console.error('❌ Erro ao criar token de grupo:', err);
      alert('Não foi possível abrir o Telegram. Tente novamente.');
    }
  });

  // ==================== BUSCA E TOGGLE ====================
  
  // Toggle sidebar (recolher/expandir lista)
  const toggleBtn = document.getElementById('toggle-sidebar');
  const sidebar = document.getElementById('sidebar');
  let sidebarCollapsed = false;

  toggleBtn.addEventListener('click', () => {
    sidebarCollapsed = !sidebarCollapsed;
    sidebar.classList.toggle('collapsed', sidebarCollapsed);
    toggleBtn.textContent = sidebarCollapsed ? '📋' : '✕';
    toggleBtn.title = sidebarCollapsed ? 'Mostrar Lista' : 'Ocultar Lista';
  });

  // Busca na lista
  const searchInput = document.getElementById('search-input');
  const clearSearchBtn = document.getElementById('clear-search');

  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase().trim();
    const listItems = document.querySelectorAll('.list-item');

    if (query === '') {
      // Mostrar todos
      listItems.forEach(item => item.classList.remove('hidden'));
      clearSearchBtn.style.display = 'none';
    } else {
      // Filtrar
      clearSearchBtn.style.display = 'block';
      listItems.forEach(item => {
        const code = item.querySelector('.pkg-code')?.textContent.toLowerCase() || '';
        const addr = item.querySelector('.pkg-addr')?.textContent.toLowerCase() || '';
        const matches = code.includes(query) || addr.includes(query);
        item.classList.toggle('hidden', !matches);
      });
    }
  });

  clearSearchBtn.addEventListener('click', () => {
    searchInput.value = '';
    searchInput.dispatchEvent(new Event('input'));
    searchInput.focus();
  });
  
  } catch(err) {
    console.error('❌ Erro fatal no map script:', err);
    console.error('Stack:', err.stack);
    document.getElementById('counter').textContent = `Erro ao inicializar mapa: ${err.message}`;
  }
})();
