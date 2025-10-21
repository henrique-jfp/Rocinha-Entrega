(function(){
  try {
    console.log('🚀 Map script iniciado');
    
    // ⚠️ PROTEÇÃO: Evita dupla inicialização
    if (window.mapInitialized) {
      console.warn('⚠️ Mapa já inicializado, ignorando nova tentativa');
      return;
    }
    window.mapInitialized = true;
    
    const body = document.body;
    const routeId = Number(body.getAttribute('data-route-id'));
    const driverId = Number(body.getAttribute('data-driver-id'));
    const botUsername = body.getAttribute('data-bot-username') || 'SEU_BOT_USERNAME';
    const baseUrl = body.getAttribute('data-base-url') || '';
    
    console.log('📍 Variáveis carregadas:', { routeId, driverId, botUsername, baseUrl });

    // Limpa container do mapa se já existir
    const mapContainer = document.getElementById('map');
    if (mapContainer._leaflet_id) {
      console.warn('🗺️ Removendo mapa anterior');
      mapContainer._leaflet_id = null;
      mapContainer.innerHTML = '';
    }

    // Initialize map - estilo Google Maps (colorido e claro)
    const map = L.map('map', {
      center: [-22.9, -43.2],
      zoom: 13,
      zoomControl: true
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
    
    // ⚠️ GLOBAL: Array de pacotes (usado pelo scanner de código de barras)
    let packages = [];

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
  
  // Define cores vibrantes para diferentes áreas - MÁXIMO 3 ÁREAS
  // Paleta sem verde/vermelho para não conflitar com status Entregue/Falhou
  const AREA_COLORS = [
    { primary: '#7c3aed', shadow: 'rgba(124, 58, 237, 0.35)', name: 'Roxo' },     // 1
    { primary: '#f59e0b', shadow: 'rgba(245, 158, 11, 0.35)', name: 'Laranja' },  // 2
    { primary: '#3b82f6', shadow: 'rgba(59, 130, 246, 0.35)', name: 'Azul' },     // 3
  ];

  // Divide pacotes em áreas geográficas usando K-means simplificado
  function divideIntoAreas(packages) {
    if (packages.length === 0) return [];
    
    // Filtra pacotes com coordenadas válidas
    const validPackages = packages.filter(p => p.latitude && p.longitude);
    if (validPackages.length === 0) return [];
    
    // Determina número de áreas (MÁXIMO 3, mínimo 2)
    const numAreas = Math.min(3, Math.max(2, Math.ceil(validPackages.length / 15)));
    
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
    // Se entregue ou falhou, mostra apenas ícone (SEM número)
    // Se pendente, mostra número
    let centerContent = '';
    
    if(status === 'delivered') {
      // PIN VERDE COM CHECKMARK (SEM NÚMERO)
      centerContent = `<div style="
        position: absolute;
        top: 6px;
        left: 6px;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #fff;
        font-weight: 900;
        font-size: 18px;
        z-index: 1;
      ">✓</div>`;
    } else if(status === 'failed') {
      // PIN VERMELHO COM X (SEM NÚMERO)
      centerContent = `<div style="
        position: absolute;
        top: 6px;
        left: 6px;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #fff;
        font-weight: 900;
        font-size: 18px;
        z-index: 1;
      ">✕</div>`;
    } else {
      // PIN COLORIDO COM NÚMERO (PENDENTE)
      centerContent = `<div style="
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
      ">${number}</div>`;
    }
    
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
      
      <!-- Conteúdo central (número OU ícone) -->
      ${centerContent}
    </div>`;
    
    return L.divIcon({
      html: html,
      className: '',
      iconSize: [36, 48],
      iconAnchor: [18, 46]
    });
  }

  function createPopupHtml(pkg){
    const hasValid = isFinite(pkg.latitude) && isFinite(pkg.longitude) && Math.abs(pkg.latitude) <= 90 && Math.abs(pkg.longitude) <= 180;
    const nav = hasValid ? `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}` : '#';
    
  // Links para Telegram: entrega e insucesso
  const deliverWeb = `https://t.me/${botUsername}?start=entrega_deliver_${pkg.id}`;
  const failWeb = `https://t.me/${botUsername}?start=entrega_fail_${pkg.id}`;
    
    const address = pkg.address || 'Sem endereço';
    const track = pkg.tracking_code || '';
    
    // Se já entregue: mostrar apenas "Concluído" sem ações
    if (pkg.status === 'delivered') {
      return `
        <div>
          <div class="popup-code">${track}</div>
          <div class="popup-addr">${address}</div>
          <div style="
            margin-top: 12px;
            padding: 12px;
            background: #d1fae5;
            border-radius: 8px;
            text-align: center;
            color: #065f46;
            font-weight: 700;
            font-size: 15px;
          ">
            ✅ Concluído - Entregue com Sucesso
          </div>
          <div style="margin-top: 8px; display: flex; justify-content: center;">
            <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener" style="
              padding: 10px 20px; text-align: center; ${hasValid ? '' : 'opacity:0.4; pointer-events:none;'}">
              🧭 Navegar para Endereço
            </a>
          </div>
        </div>`;
    }
    
    // Se falhou: mantém botão "Entregar" para nova tentativa
    if (pkg.status === 'failed') {
      return `
        <div>
          <div class="popup-code">${track}</div>
          <div class="popup-addr">${address}</div>
          <div style="
            margin-top: 12px;
            padding: 12px;
            background: #fee2e2;
            border-radius: 8px;
            text-align: center;
            color: #991b1b;
            font-weight: 700;
            font-size: 14px;
            margin-bottom: 8px;
          ">
            ❌ Insucesso Registrado
          </div>
          <div style="
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #e5e7eb;
            display: flex;
            gap: 6px;
            flex-direction: column;
          ">
            <a class="popup-btn deliver" href="${deliverWeb}" target="_blank" rel="noopener" style="
              display: block; text-align: center; background: #10b981; color: white; font-weight: 800; border: 1px solid #059669; border-radius: 10px; padding: 10px; font-size: 14px; text-decoration: none;">
              ✓ Tentar Entregar Novamente
            </a>
            <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener" style="
              display: block; text-align: center; padding: 10px; ${hasValid ? '' : 'opacity:0.4; pointer-events:none;'}">
              🧭 Navegar para Endereço
            </a>
          </div>
        </div>`;
    }
    
    // Pendente: fluxo normal
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
          <div style="display: flex; gap: 6px; align-items: center;">
            <a class="popup-btn deliver" href="${deliverWeb}" target="_blank" rel="noopener" style="
              flex: 2; text-align: center; background: #10b981; color: white; font-weight: 800; border: 1px solid #059669; border-radius: 10px; padding: 10px; font-size: 14px; text-decoration: none;">
              ✓ Entregar
            </a>
            <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener" style="
              flex: 1; text-align: center; ${hasValid ? '' : 'opacity:0.4; pointer-events:none;'}">
              🧭 Navegar
            </a>
          </div>
          <div style="display:flex; gap:6px; margin-top:6px;">
            <button onclick="markPackageDelivered(${pkg.id})" style="
              padding: 8px 12px; background: #16a34a; color: white; border: none; border-radius: 6px; font-weight: 600; font-size: 13px; cursor: pointer; transition: all 0.2s; flex:1;" 
              onmouseover="this.style.background='#15803d'" onmouseout="this.style.background='#16a34a'">
              ✅ Marcar Entregue (Rápido)
            </button>
            <a class="popup-btn fail" href="${failWeb}" target="_blank" rel="noopener" style="
              flex:1; text-align:center; background:#ef4444; color:white; border-radius:6px; padding:8px 12px; font-weight:600; font-size:13px; text-decoration:none;">
              ❌ Insucesso
            </a>
          </div>
        </div>
      </div>`;
  }

  // Popup para cluster com múltiplos pacotes
  function createClusterPopupHtml(packages){
    const firstPkg = packages[0];
    const valid = isFinite(firstPkg.latitude) && isFinite(firstPkg.longitude) && Math.abs(firstPkg.latitude) <= 90 && Math.abs(firstPkg.longitude) <= 180;
    const nav = valid ? `https://www.google.com/maps?q=${firstPkg.latitude},${firstPkg.longitude}` : '#';
    
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
              <a href="https://t.me/${botUsername}?start=entrega_fail_${pkg.id}" target="_blank" rel="noopener" style="
                font-size: 10px; padding: 2px 6px; background: #ef4444; color: white; border-radius: 4px; text-decoration: none; font-weight: 700;">❌ Insucesso</a>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');

    // Link para entregar todos com token curto (evita limite de 64 chars do Telegram)
    const pendingIds = packages.filter(p => p.status === 'pending').map(p => p.id);
    const pendingCount = pendingIds.length;
    
    return `
      <div style="min-width: 300px; max-width: 360px;">
        <div style="
          background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
          color: white;
          padding: 14px;
          margin: -12px -12px 12px -12px;
          border-radius: 8px 8px 0 0;
          font-weight: 700;
          font-size: 15px;
        ">
          📍 ${packages.length} Pacote${packages.length > 1 ? 's' : ''} nesta Parada
        </div>
        
        <div style="max-height: 280px; overflow-y: auto; margin-bottom: 12px;">
          ${packagesList}
        </div>
        
        <!-- BOTÃO GRANDE DE ENTREGAR NO TOPO -->
        ${pendingCount > 0 ? `
          <a class="popup-btn deliver deliver-all" href="#" data-ids="${pendingIds.join(',')}" style="
            display: block;
            width: 100%;
            text-align: center;
            background: #10b981;
            color: white;
            font-size: 16px;
            font-weight: 800;
            padding: 14px;
            border: none;
            border-radius: 12px;
            text-decoration: none;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
            margin-bottom: 10px;
            transition: all 0.2s;
          " onmouseover="this.style.background='#059669'; this.style.transform='scale(1.02)'" onmouseout="this.style.background='#10b981'; this.style.transform='scale(1)'">
            ✓ ENTREGAR TODOS (${pendingCount})
          </a>
        ` : ''}
        
        <!-- 3 BOTÕES PEQUENOS EMBAIXO -->
        <div style="display: flex; gap: 8px; align-items: center;">
          ${pendingCount > 0 ? `
            <button onclick="event.stopPropagation(); ${pendingIds.map(id => `markPackageDelivered(${id})`).join('; ')};" style="
              flex: 1;
              padding: 10px;
              background: #10b981;
              color: white;
              border: none;
              border-radius: 8px;
              font-size: 13px;
              font-weight: 700;
              cursor: pointer;
              transition: all 0.2s;
            " onmouseover="this.style.background='#059669'" onmouseout="this.style.background='#10b981'">
              ✓ Marcar
            </button>
            <a href="https://t.me/${botUsername}?start=entrega_fail_${pendingIds[0]}" target="_blank" rel="noopener" style="
              flex: 1;
              padding: 10px;
              background: #ef4444;
              color: white;
              border-radius: 8px;
              font-size: 13px;
              font-weight: 700;
              text-align: center;
              text-decoration: none;
              transition: all 0.2s;
            " onmouseover="this.style.background='#dc2626'" onmouseout="this.style.background='#ef4444'">
              ✕ Insucesso
            </a>
          ` : ''}
          <a class="popup-btn nav" href="${nav}" target="_blank" rel="noopener" style="
            flex: 1;
            padding: 10px;
            background: #3b82f6;
            color: white;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 700;
            text-align: center;
            text-decoration: none;
            transition: all 0.2s;
            ${valid ? '' : 'opacity:0.4; pointer-events:none;'}
          " onmouseover="this.style.background='#2563eb'" onmouseout="this.style.background='#3b82f6'">
            🧭 Ir
          </a>
        </div>
      </div>
    `;
  }

  // Adiciona marcador individual
  function addPackageMarker(pkg, index){
    // Validação robusta de coordenadas
    if(!pkg.latitude || !pkg.longitude) {
      console.warn(`⚠️ Pacote ${pkg.code || 'desconhecido'} sem coordenadas`);
      return null;
    }
    if(!isFinite(pkg.latitude) || !isFinite(pkg.longitude)) {
      console.warn(`⚠️ Pacote ${pkg.code || 'desconhecido'} com coordenadas inválidas:`, pkg.latitude, pkg.longitude);
      return null;
    }
    if(Math.abs(pkg.latitude) > 90 || Math.abs(pkg.longitude) > 180) {
      console.warn(`⚠️ Pacote ${pkg.code || 'desconhecido'} com coordenadas fora do intervalo válido`);
      return null;
    }
    
    try {
      const icon = createNumberedIcon(index + 1, pkg.status, false, pkg.areaColor);
      const marker = L.marker([pkg.latitude, pkg.longitude], { icon }).addTo(markersLayer);
      marker.bindPopup(createPopupHtml(pkg));
      marker.pkg = pkg;
      return marker;
    } catch(error) {
      console.error(`❌ Erro ao criar marker para pacote ${pkg.code || 'desconhecido'}:`, error);
      return null;
    }
  }

  // Adiciona marcador de cluster
  function addClusterMarker(cluster, clusterIndex){
    const packages = cluster.packages;
    const count = packages.length;
    
    // Validação de coordenadas do cluster
    if(!cluster.lat || !cluster.lng) {
      console.warn(`⚠️ Cluster ${clusterIndex} sem coordenadas`);
      return null;
    }
    if(!isFinite(cluster.lat) || !isFinite(cluster.lng)) {
      console.warn(`⚠️ Cluster ${clusterIndex} com coordenadas inválidas:`, cluster.lat, cluster.lng);
      return null;
    }
    if(Math.abs(cluster.lat) > 90 || Math.abs(cluster.lng) > 180) {
      console.warn(`⚠️ Cluster ${clusterIndex} com coordenadas fora do intervalo válido`);
      return null;
    }
    
    // Determina status dominante do cluster
    const statuses = packages.map(p => p.status);
    let dominantStatus = 'pending';
    if(statuses.every(s => s === 'delivered')) dominantStatus = 'delivered';
    else if(statuses.every(s => s === 'failed')) dominantStatus = 'failed';
    
    // Usa cor do primeiro pacote do cluster
    const areaColor = packages[0].areaColor || null;
    
    try {
      const icon = createNumberedIcon(clusterIndex + 1, dominantStatus, true, areaColor);
      const marker = L.marker([cluster.lat, cluster.lng], { icon }).addTo(markersLayer);
      marker.bindPopup(createClusterPopupHtml(packages), { maxWidth: 340 });
      marker.cluster = cluster;
      return marker;
    } catch(error) {
      console.error(`❌ Erro ao criar marker do cluster ${clusterIndex}:`, error);
      return null;
    }
  }

  function getStatusText(status){
    if(status === 'delivered') return 'Entregue';
    if(status === 'failed') return 'Falhou';
    return 'Pendente';
  }

  function createListItem(pkg, marker, index){
    const li = document.createElement('li');
    li.className = `list-item ${pkg.status}`;
    li.style.cssText = `
      padding: 12px;
      border-bottom: 1px solid #e5e7eb;
      cursor: pointer;
      transition: background 0.2s;
      position: relative;
      display: flex;
      flex-direction: column;
      gap: 10px;
    `;

    // Indicador de cor de área
    if (pkg.areaColor && pkg.status === 'pending') {
      const areaIndicator = document.createElement('div');
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
    }

    // Container superior: pin + info + badge
    const topRow = document.createElement('div');
    topRow.style.cssText = 'display: flex; align-items: center; gap: 12px;';

    const pinNum = document.createElement('div');
    pinNum.style.cssText = `
      flex-shrink: 0;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: ${pkg.status === 'delivered' ? '#10b981' : pkg.status === 'failed' ? '#ef4444' : (pkg.areaColor?.primary || '#9333ea')};
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 14px;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
    `;
    pinNum.textContent = index + 1;

    const info = document.createElement('div');
    info.style.cssText = 'flex: 1; min-width: 0;';

    // ENDEREÇO EM DESTAQUE (principal)
    const addr = document.createElement('div');
    addr.style.cssText = `
      font-size: 14px;
      font-weight: 600;
      color: #1f2937;
      line-height: 1.3;
      margin-bottom: 4px;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    `;
    addr.textContent = pkg.address || 'Sem endereço';

    // Código de rastreio (secundário, menor)
    const code = document.createElement('div');
    code.style.cssText = `
      font-size: 11px;
      color: #9ca3af;
      font-weight: 500;
      font-family: 'SF Mono', 'Consolas', monospace;
    `;
    code.textContent = pkg.tracking_code || 'Sem código';

    info.appendChild(addr);
    info.appendChild(code);

    const badge = document.createElement('div');
    badge.style.cssText = `
      flex-shrink: 0;
      font-size: 10px;
      font-weight: 700;
      padding: 4px 8px;
      border-radius: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      ${pkg.status === 'pending' ? 'background: #dbeafe; color: #1e40af;' : ''}
      ${pkg.status === 'delivered' ? 'background: #d1fae5; color: #065f46;' : ''}
      ${pkg.status === 'failed' ? 'background: #fee2e2; color: #991b1b;' : ''}
    `;
    badge.textContent = getStatusText(pkg.status);

    topRow.appendChild(pinNum);
    topRow.appendChild(info);
    topRow.appendChild(badge);

    // BOTÕES: Entregar grande no topo, 3 pequenos embaixo
    const buttonsContainer = document.createElement('div');
    buttonsContainer.style.cssText = 'display: flex; flex-direction: column; gap: 6px; margin-top: 4px;';

    if (pkg.status === 'pending') {
      // BOTÃO GRANDE: ENTREGAR
      const deliverBtn = document.createElement('a');
      deliverBtn.href = `https://t.me/${botUsername}?start=entrega_deliver_${pkg.id}`;
      deliverBtn.target = '_blank';
      deliverBtn.rel = 'noopener';
      deliverBtn.style.cssText = `
        display: block;
        text-align: center;
        padding: 12px;
        background: #10b981;
        color: white;
        border-radius: 10px;
        font-size: 14px;
        font-weight: 800;
        text-decoration: none;
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
        transition: all 0.2s;
      `;
      deliverBtn.textContent = '✓ ENTREGAR';
      deliverBtn.addEventListener('mouseover', () => {
        deliverBtn.style.background = '#059669';
        deliverBtn.style.transform = 'scale(1.02)';
      });
      deliverBtn.addEventListener('mouseout', () => {
        deliverBtn.style.background = '#10b981';
        deliverBtn.style.transform = 'scale(1)';
      });

      // 3 BOTÕES PEQUENOS
      const smallBtnsRow = document.createElement('div');
      smallBtnsRow.style.cssText = 'display: flex; gap: 6px;';

      // Botão 1: Marcar Entregue (✓)
      const markBtn = document.createElement('button');
      markBtn.style.cssText = `
        flex: 1;
        padding: 8px;
        background: #10b981;
        color: white;
        border: none;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.2s;
      `;
      markBtn.textContent = '✓ Marcar';
      markBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await markPackageDelivered(pkg.id);
      });
      markBtn.addEventListener('mouseover', () => markBtn.style.background = '#059669');
      markBtn.addEventListener('mouseout', () => markBtn.style.background = '#10b981');

      // Botão 2: Insucesso (✕)
      const failBtn = document.createElement('a');
      failBtn.href = `https://t.me/${botUsername}?start=entrega_fail_${pkg.id}`;
      failBtn.target = '_blank';
      failBtn.rel = 'noopener';
      failBtn.style.cssText = `
        flex: 1;
        padding: 8px;
        background: #ef4444;
        color: white;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        text-align: center;
        text-decoration: none;
        transition: all 0.2s;
      `;
      failBtn.textContent = '✕ Falha';
      failBtn.addEventListener('mouseover', () => failBtn.style.background = '#dc2626');
      failBtn.addEventListener('mouseout', () => failBtn.style.background = '#ef4444');

      // Botão 3: Navegar (🧭)
      const navBtn = document.createElement('a');
      navBtn.target = '_blank';
      navBtn.rel = 'noopener';
      navBtn.style.cssText = `
        flex: 1;
        padding: 8px;
        background: #3b82f6;
        color: white;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        text-align: center;
        text-decoration: none;
        transition: all 0.2s;
      `;
      navBtn.textContent = '🧭 Ir';
      
      if (isFinite(pkg.latitude) && isFinite(pkg.longitude) && Math.abs(pkg.latitude) <= 90 && Math.abs(pkg.longitude) <= 180) {
        navBtn.href = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
      } else {
        navBtn.href = '#';
        navBtn.style.opacity = '0.4';
        navBtn.style.pointerEvents = 'none';
      }
      navBtn.addEventListener('mouseover', () => navBtn.style.background = '#2563eb');
      navBtn.addEventListener('mouseout', () => navBtn.style.background = '#3b82f6');

      smallBtnsRow.appendChild(markBtn);
      smallBtnsRow.appendChild(failBtn);
      smallBtnsRow.appendChild(navBtn);

      buttonsContainer.appendChild(deliverBtn);
      buttonsContainer.appendChild(smallBtnsRow);
    } else {
      // Pacote já entregue/falhou - apenas botão de navegação
      const navBtn = document.createElement('a');
      navBtn.target = '_blank';
      navBtn.rel = 'noopener';
      navBtn.style.cssText = `
        display: block;
        text-align: center;
        padding: 10px;
        background: #3b82f6;
        color: white;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 700;
        text-decoration: none;
        transition: all 0.2s;
      `;
      navBtn.textContent = '🧭 Navegar';
      
      if (isFinite(pkg.latitude) && isFinite(pkg.longitude) && Math.abs(pkg.latitude) <= 90 && Math.abs(pkg.longitude) <= 180) {
        navBtn.href = `https://www.google.com/maps?q=${pkg.latitude},${pkg.longitude}`;
      } else {
        navBtn.href = '#';
        navBtn.style.opacity = '0.4';
        navBtn.style.pointerEvents = 'none';
      }
      navBtn.addEventListener('mouseover', () => navBtn.style.background = '#2563eb');
      navBtn.addEventListener('mouseout', () => navBtn.style.background = '#3b82f6');

      buttonsContainer.appendChild(navBtn);
    }

    li.appendChild(topRow);
    li.appendChild(buttonsContainer);

    li.addEventListener('click', (e)=>{
      if(e.target.tagName.toLowerCase() === 'a' || e.target.tagName.toLowerCase() === 'button') return;
      if(marker){
        map.flyTo(marker.getLatLng(), 16, { duration: 0.5 });
        setTimeout(() => marker.openPopup(), 600);
      }
    });

    return li;
  }

  // Função para marcar pacote como entregue (GLOBAL para funcionar nos popups)
  window.markPackageDelivered = async function(packageId) {
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
  };

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
      
      // ⚠️ Salva pacotes na variável global para uso do scanner
      packages = data;

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
          if(marker){
            const latLng = marker.getLatLng();
            if(latLng && isFinite(latLng.lat) && isFinite(latLng.lng)){
              group.push(latLng);
            }
          }
          list.appendChild(createListItem(pkg, marker, displayIndex));
          displayIndex++;
        } else {
          // Parada com múltiplos pacotes no mesmo endereço
          const marker = addClusterMarker(cluster, displayIndex);
          if(marker){
            const latLng = marker.getLatLng();
            if(latLng && isFinite(latLng.lat) && isFinite(latLng.lng)){
              group.push(latLng);
            }
          }
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

      // Ajusta zoom para mostrar todos os pacotes
      if(group.length > 0){
        try {
          // Filtra coordenadas válidas
          const validCoords = group.filter(coord => {
            return coord &&
                   typeof coord.lat === 'number' &&
                   typeof coord.lng === 'number' &&
                   isFinite(coord.lat) &&
                   isFinite(coord.lng) &&
                   Math.abs(coord.lat) <= 90 &&
                   Math.abs(coord.lng) <= 180;
          });

          if (validCoords.length === 1) {
            map.setView(validCoords[0], 15);
            console.log('✅ Zoom definido em um único ponto');
          } else if (validCoords.length > 1) {
            try {
              const latLngs = validCoords.map(c => L.latLng(c.lat, c.lng));
              const bounds = L.latLngBounds(latLngs);
              if(bounds.isValid()){
                map.fitBounds(bounds.pad(0.12));
                console.log('✅ Zoom ajustado para', validCoords.length, 'pontos');
              } else {
                console.warn('⚠️ Bounds inválidos (isValid=false). Fallback setView no primeiro ponto.');
                map.setView(validCoords[0], 13);
              }
            } catch (innerErr) {
              console.warn('⚠️ fitBounds falhou. Aplicando fallback de média dos pontos.', innerErr);
              const avg = validCoords.reduce((acc, p) => ({ lat: acc.lat + p.lat, lng: acc.lng + p.lng }), { lat: 0, lng: 0 });
              avg.lat /= validCoords.length;
              avg.lng /= validCoords.length;
              if (isFinite(avg.lat) && isFinite(avg.lng)) {
                map.setView([avg.lat, avg.lng], 13);
              }
            }
          } else {
            console.warn('⚠️ Nenhuma coordenada válida para ajustar bounds.');
          }
        } catch(boundsError) {
          console.error('❌ Erro ao ajustar bounds (nível externo):', boundsError);
        }
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
    if(!isFinite(lat) || !isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
      console.warn('⚠️ Localização inválida ignorada:', { lat, lng });
      return;
    }
    try {
      if (myMarker) {
        myMarker.setLatLng([lat, lng]);
      } else {
        const dotIcon = L.divIcon({
          className: '',
          html: `<div style="
              width: 14px; height: 14px; border-radius: 50%;
              background: #2563eb; border: 3px solid #fff; box-shadow: 0 0 0 6px rgba(37,99,235,0.25);
            "></div>`,
          iconSize: [14, 14],
          iconAnchor: [7, 7]
        });
        myMarker = L.marker([lat, lng], { icon: dotIcon, keyboard: false, interactive: false });
        myMarker.addTo(myLocationLayer);
      }
    } catch (e) {
      console.error('❌ Erro ao posicionar localização do motorista:', e);
    }
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

  // No mobile, abre com a lista recolhida para o mapa aparecer
  if (window.innerWidth <= 768) {
    sidebarCollapsed = true;
    sidebar.classList.add('collapsed');
    toggleBtn.textContent = '📋';
    toggleBtn.title = 'Mostrar Lista';
  }

  toggleBtn.addEventListener('click', () => {
    sidebarCollapsed = !sidebarCollapsed;
    sidebar.classList.toggle('collapsed', sidebarCollapsed);
    toggleBtn.textContent = sidebarCollapsed ? '📋' : '✕';
    toggleBtn.title = sidebarCollapsed ? 'Mostrar Lista' : 'Ocultar Lista';
    // Dá tempo da transição finalizar e ajusta o mapa
    setTimeout(() => {
      try { map.invalidateSize(); } catch {}
    }, 320);
  });

  // Ajusta estado ao mudar orientação/tamanho
  window.addEventListener('resize', () => {
    const isMobile = window.innerWidth <= 768;
    if (isMobile && !sidebarCollapsed) {
      sidebarCollapsed = true;
      sidebar.classList.add('collapsed');
      toggleBtn.textContent = '📋';
      toggleBtn.title = 'Mostrar Lista';
    }
    if (!isMobile && sidebarCollapsed) {
      sidebarCollapsed = false;
      sidebar.classList.remove('collapsed');
      toggleBtn.textContent = '✕';
      toggleBtn.title = 'Ocultar Lista';
    }
    try { map.invalidateSize(); } catch {}
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

  // ================================================================================
  // SCANNER DE CÓDIGO DE BARRAS
  // ================================================================================

  let barcodeScanner = null;
  let scannerStream = null;

  // Carrega biblioteca ZXing para leitura de códigos
  function loadZXingLibrary() {
    if (window.ZXing) {
      console.log('✅ ZXing já carregado');
      return Promise.resolve();
    }
    
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/@zxing/library@0.19.1/umd/index.min.js';
      script.onload = () => {
        console.log('✅ Biblioteca ZXing carregada');
        resolve();
      };
      script.onerror = () => {
        console.error('❌ Erro ao carregar ZXing');
        reject(new Error('Falha ao carregar biblioteca de scanner'));
      };
      document.head.appendChild(script);
    });
  }

  // Inicializa scanner
  async function initBarcodeScanner() {
    if (!window.ZXing) {
      await loadZXingLibrary();
    }
    
    const { BrowserMultiFormatReader } = window.ZXing;
    barcodeScanner = new BrowserMultiFormatReader();
    console.log('✅ Scanner de código de barras inicializado');
  }

  // Abre modal do scanner
  window.scanAndDeliver = async function() {
    try {
      console.log('📷 Iniciando scanner de código de barras...');
      
      // Mostra modal com preview da camera
      const modal = document.createElement('div');
      modal.id = 'scanner-modal';
      modal.innerHTML = `
        <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
                    background: rgba(0,0,0,0.95); z-index: 10000; display: flex; 
                    flex-direction: column; align-items: center; justify-content: center;">
          <div style="color: white; margin-bottom: 15px; font-size: 20px; font-weight: bold; text-align: center; padding: 0 20px;">
            📷 Aponte para o código de barras do pacote
          </div>
          <div style="position: relative; width: 90%; max-width: 500px;">
            <video id="scanner-video" autoplay playsinline 
                   style="width: 100%; border: 3px solid #4CAF50; border-radius: 10px; background: #000;"></video>
            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
                        width: 80%; height: 30%; border: 2px solid #4CAF50; border-radius: 5px;
                        pointer-events: none; box-shadow: 0 0 0 9999px rgba(0,0,0,0.5);"></div>
          </div>
          <div id="scanner-status" style="color: #4CAF50; margin-top: 15px; font-size: 16px; text-align: center;">
            Aguardando código...
          </div>
          <button onclick="closeScannerModal()" 
                  style="margin-top: 20px; padding: 15px 40px; font-size: 18px; font-weight: bold;
                         background: #f44336; color: white; border: none; border-radius: 8px;
                         cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            ❌ Cancelar
          </button>
        </div>
      `;
      document.body.appendChild(modal);
      
      // Inicializa scanner se necessário
      if (!barcodeScanner) {
        document.getElementById('scanner-status').textContent = 'Carregando scanner...';
        await initBarcodeScanner();
      }
      
      const videoElement = document.getElementById('scanner-video');
      document.getElementById('scanner-status').textContent = 'Aguardando código...';
      
      // Inicia leitura da camera
      scannerStream = await barcodeScanner.decodeFromVideoDevice(
        null, // Usa camera padrão (traseira em celulares)
        'scanner-video',
        (result, error) => {
          if (result) {
            const barcode = result.text;
            console.log('✅ Código detectado:', barcode);
            document.getElementById('scanner-status').textContent = `✅ Código: ${barcode}`;
            
            // Para o scanner e fecha modal
            closeScannerModal();
            
            // Busca pacote e inicia entrega
            findPackageAndDeliver(barcode);
          }
          
          if (error && error.name !== 'NotFoundException') {
            console.warn('⚠️ Erro no scanner:', error.message);
          }
        }
      );
      
    } catch (error) {
      console.error('❌ Erro ao abrir scanner:', error);
      alert('❌ Erro ao acessar camera: ' + error.message + '\n\nVerifique as permissões de camera.');
      closeScannerModal();
    }
  };

  // Fecha modal do scanner
  window.closeScannerModal = function() {
    console.log('🔒 Fechando scanner...');
    
    // Para o scanner
    if (barcodeScanner) {
      try {
        barcodeScanner.reset();
      } catch (e) {
        console.warn('Erro ao resetar scanner:', e);
      }
    }
    
    // Para o stream de video
    if (scannerStream) {
      try {
        const videoElement = document.getElementById('scanner-video');
        if (videoElement && videoElement.srcObject) {
          const tracks = videoElement.srcObject.getTracks();
          tracks.forEach(track => track.stop());
        }
      } catch (e) {
        console.warn('Erro ao parar stream:', e);
      }
      scannerStream = null;
    }
    
    // Remove modal
    const modal = document.getElementById('scanner-modal');
    if (modal) {
      modal.remove();
    }
  };

  // Busca pacote pelo código e inicia entrega
  async function findPackageAndDeliver(barcode) {
    try {
      console.log('🔍 Buscando pacote com código:', barcode);
      
      // Busca nos pacotes carregados
      const pkg = packages.find(p => 
        p.tracking_code === barcode && p.status === 'pending'
      );
      
      if (!pkg) {
        // Tenta buscar variações (sem espaços, maiúscula/minúscula)
        const normalizedBarcode = barcode.trim().toUpperCase();
        const pkgVariant = packages.find(p => 
          p.tracking_code.trim().toUpperCase() === normalizedBarcode && 
          p.status === 'pending'
        );
        
        if (pkgVariant) {
          console.log('✅ Pacote encontrado (variação):', pkgVariant);
          confirmAndStartDelivery(pkgVariant, barcode);
          return;
        }
        
        alert(
          `❌ Pacote não encontrado!\n\n` +
          `Código: ${barcode}\n\n` +
          `Possíveis motivos:\n` +
          `• Pacote já foi entregue\n` +
          `• Código não está nesta rota\n` +
          `• Código incorreto\n\n` +
          `Tente novamente ou entregue manualmente.`
        );
        return;
      }
      
      console.log('✅ Pacote encontrado:', pkg);
      confirmAndStartDelivery(pkg, barcode);
      
    } catch (error) {
      console.error('❌ Erro ao buscar pacote:', error);
      alert('❌ Erro ao buscar pacote: ' + error.message);
    }
  }

  // Confirma e inicia entrega
  function confirmAndStartDelivery(pkg, barcode) {
    // Destaca o pacote no mapa
    map.setView([pkg.latitude, pkg.longitude], 17, { animate: true });
    
    // Mostra confirmação
    const confirmed = confirm(
      `✅ Pacote Encontrado!\n\n` +
      `📦 Código: ${barcode}\n` +
      `📍 Endereço: ${pkg.address}\n` +
      `🏘️ Bairro: ${pkg.neighborhood || 'N/A'}\n\n` +
      `Deseja iniciar o processo de entrega no Telegram?`
    );
    
    if (confirmed) {
      console.log('🚀 Iniciando entrega via Telegram para pacote:', pkg.id);
      startDelivery(pkg.id);
    }
  }

  // Pré-carrega biblioteca ao iniciar mapa
  loadZXingLibrary().catch(err => {
    console.warn('⚠️ Não foi possível pré-carregar ZXing:', err);
  });
  
  } catch(err) {
    console.error('❌ Erro fatal no map script:', err);
    console.error('Stack:', err.stack);
    document.getElementById('counter').textContent = `Erro ao inicializar mapa: ${err.message}`;
  }
})();
