// Global State Variables
let currentView = 'chat';
let chatHistory = [];
let recentChats = [];
let userLocation = { lat: null, lon: null, text: 'Detecting location…' };
let searchMode = 'gps'; // 'gps' or 'manual'
let detectedSpecialty = 'multispeciality hospital OR general hospital OR medical clinic';
let leafMap = null;
let leafMarkers = [];
let selectedHospitalForBooking = null;

// Initialize app when DOM loads
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    detectUserLocation();
    loadRecentChats();
    switchView('chat');
    
    // Setup Drag and Drop listeners
    const dragZone = document.getElementById('drag-zone');
    if (dragZone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dragZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dragZone.classList.add('drag-active');
            }, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            dragZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dragZone.classList.remove('drag-active');
            }, false);
        });
        
        dragZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length > 0) {
                document.getElementById('image-uploader').files = files;
                handleSelectedFile(files[0]);
            }
        }, false);
    }
});

// ==========================================
// THEME MANAGEMENT
// ==========================================
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    const body = document.body;
    const toggle = document.getElementById('theme-toggle');

    if (savedTheme === 'dark') {
        body.classList.remove('light-mode');
        body.classList.add('dark-mode');
        if (toggle) toggle.checked = true;
    } else {
        body.classList.remove('dark-mode');
        body.classList.add('light-mode');
        if (toggle) toggle.checked = false;
    }

    // Apply saved sidebar state
    const collapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    if (collapsed) {
        document.body.classList.add('collapsed');
        const btn = document.getElementById('sidebar-toggle');
        if (btn) btn.innerHTML = '→';
    }
}

function toggleTheme() {
    const body = document.body;
    const toggle = document.getElementById('theme-toggle');
    
    if (toggle.checked) {
        body.classList.remove('light-mode');
        body.classList.add('dark-mode');
        localStorage.setItem('theme', 'dark');
    } else {
        body.classList.remove('dark-mode');
        body.classList.add('light-mode');
        localStorage.setItem('theme', 'light');
    }
}

// ==========================================
// VIEW ROUTER
// ==========================================
function switchView(viewName) {
    currentView = viewName;
    
    // Update active nav button
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.remove('active');
    });
    
    const activeNav = document.getElementById(`nav-${viewName}`);
    if (activeNav) activeNav.classList.add('active');
    
    // Show active section, hide others
    document.querySelectorAll('.view-section').forEach(sec => {
        sec.classList.remove('active');
    });
    
    const activeSec = document.getElementById(`${viewName}-view`);
    if (activeSec) activeSec.classList.add('active');
    
    // Update topbar descriptions
    const title = document.getElementById('page-title');
    const sub = document.getElementById('page-sub');
    
    if (viewName === 'chat') {
        title.innerText = 'Medical AI Assistant';
        sub.innerText = 'Ask anything about health, symptoms, or medications';
    } else if (viewName === 'image') {
        title.innerText = 'Medical Image Analyzer';
        sub.innerText = 'Upload details of a rash, skin condition or wound for LLM report';
    } else if (viewName === 'hospitals') {
        title.innerText = 'Find Nearby Hospitals';
        sub.innerText = 'Locate medical services near you based on conditions';
        // Lazy initialize or refresh map
        setTimeout(initOrRefreshMap, 100);
    } else if (viewName === 'appointments') {
        title.innerText = 'My Appointments';
        sub.innerText = 'View currently scheduled health consultations';
        loadAppointments();
    }
}

// ==========================================
// GEOLOCATION
// ==========================================
function detectUserLocation() {
    const statusText = document.getElementById('loc-status-text');
    const onlineStatus = document.getElementById('online-status');
    
    if (!navigator.geolocation) {
        userLocation.text = 'Location not supported';
        if (statusText) statusText.innerText = userLocation.text;
        if (onlineStatus) onlineStatus.innerText = 'Online · GPS Unavailable';
        return;
    }
    
    navigator.geolocation.getCurrentPosition(
        async (position) => {
            userLocation.lat = position.coords.latitude;
            userLocation.lon = position.coords.longitude;
            
            // Call reverse geocoding API to resolve readable city name
            try {
                const response = await fetch('/api/reverse-geocode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lat: userLocation.lat, lon: userLocation.lon })
                });
                const data = await response.json();
                if (data.location) {
                    userLocation.text = data.location;
                } else {
                    userLocation.text = `${userLocation.lat.toFixed(4)}, ${userLocation.lon.toFixed(4)}`;
                }
            } catch (err) {
                userLocation.text = `${userLocation.lat.toFixed(4)}, ${userLocation.lon.toFixed(4)}`;
            }
            
            if (statusText) statusText.innerText = userLocation.text;
            if (onlineStatus) onlineStatus.innerText = `Online · ${userLocation.text}`;
            
            // Pre-fill manual search with resolved city name
            const cityInput = document.getElementById('city-search-input');
            if (cityInput && userLocation.text) {
                cityInput.value = userLocation.text.split(',').pop().trim();
            }
        },
        (error) => {
            console.error('Geolocation error:', error);
            userLocation.text = 'Location Access Denied';
            if (statusText) statusText.innerText = userLocation.text;
            if (onlineStatus) onlineStatus.innerText = 'Online · Search manually';
            // Switch search mode to manual since GPS failed
            setSearchMode('manual');
        }
    );
}

// ==========================================
// CHAT BOT MODULE
// ==========================================
function handleChatKey(e) {
    if (e.key === 'Enter') {
        sendChatMessage();
    }
}

function sendSuggestion(text) {
    const input = document.getElementById('chat-input');
    if (input) {
        input.value = text;
        sendChatMessage();
    }
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    if (!input) return;
    
    const text = input.value.trim();
    if (!text) return;
    
    // Clear input
    input.value = '';
    
    // Hide welcome screen if visible
    const welcome = document.getElementById('welcome-screen');
    if (welcome) welcome.style.display = 'none';
    
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    // Add user message to history
    const userMsg = { role: 'user', content: text, time: time };
    chatHistory.push(userMsg);
    saveRecentChat(text);
    renderChatMessages();
    
    // Add bot loading state
    const chatHistEl = document.getElementById('chat-history');
    const loadId = 'loading-bot-msg';
    const loadHtml = `
        <div class="chat-msg bot" id="${loadId}">
            <div class="msg-avatar bot">H</div>
            <div class="msg-bubble-wrapper">
                <div class="msg-bubble bot">
                    <div class="shimmer-wrapper">
                        <div class="shimmer-line body-1"></div>
                        <div class="shimmer-line body-2"></div>
                        <div class="shimmer-line body-3"></div>
                    </div>
                </div>
            </div>
        </div>
    `;
    chatHistEl.insertAdjacentHTML('beforeend', loadHtml);
    chatHistEl.scrollTop = chatHistEl.scrollHeight;
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });
        
        // Remove loading state
        const loadEl = document.getElementById(loadId);
        if (loadEl) loadEl.remove();
        
        if (!response.ok) {
            throw new Error('API server returned error');
        }
        
        const data = await response.json();

        // Add bot response to history
        const botMsg = {
            role: 'bot',
            content: data.answer,
            time: time,
            sources: data.sources || []
        };
        chatHistory.push(botMsg);
        renderChatMessages();

        // Update detected specialty + auto-fetch nearby hospitals into the chat
        if (data.specialty) {
            detectedSpecialty = data.specialty;

            const cleanSpecialty = detectedSpecialty.split('OR')[0].trim();
            const specialtyLabel = document.getElementById('detected-specialty-text');
            if (specialtyLabel) specialtyLabel.innerText = cleanSpecialty;

            if (userLocation.lat !== null && userLocation.lon !== null) {
                await fetchHospitalsIntoChat(userLocation.lat, userLocation.lon, detectedSpecialty);
            }
        }

    } catch (err) {
        console.error(err);
        const loadEl = document.getElementById(loadId);
        if (loadEl) loadEl.remove();
        
        chatHistory.push({
            role: 'bot',
            content: '⚠️ Sorry, there was an issue communicating with the Healix Knowledge base. Please ensure Groq keys are active.',
            time: time
        });
    }
    
    renderChatMessages();
}

function renderChatMessages() {
    const chatHistEl = document.getElementById('chat-history');
    if (!chatHistEl) return;
    
    chatHistEl.innerHTML = '';
    
    chatHistory.forEach(msg => {
        // Hospital recommendation messages get their own card layout,
        // rendered inline in the chat (not a separate view/page).
        if (msg.role === 'hospital') {
            const cardsHtml = buildHospitalCardsHtml(msg.hospitals || []);
            const hospitalHtml = `
                <div class="chat-msg hospital">
                    <div class="msg-avatar bot">H</div>
                    <div class="msg-bubble-wrapper">
                        <div class="msg-bubble hospital hospital-msg-cards">
                            ${cardsHtml}
                        </div>
                        <div class="msg-time">${msg.time || ''}</div>
                    </div>
                </div>
            `;
            chatHistEl.insertAdjacentHTML('beforeend', hospitalHtml);
            return;
        }

        const isUser = msg.role === 'user';
        let sourcesHtml = '';
        
        if (!isUser && msg.sources && msg.sources.length > 0) {
            const pills = msg.sources.map(src => `<span class="src-pill">${src}</span>`).join('');
            sourcesHtml = `<div class="msg-sources">${pills}</div>`;
        }
        
        const msgHtml = `
            <div class="chat-msg ${msg.role}">
                <div class="msg-avatar ${msg.role}">${isUser ? 'You' : 'H'}</div>
                <div class="msg-bubble-wrapper">
                    <div class="msg-bubble ${msg.role}">${msg.content}${sourcesHtml}</div>
                    <div class="msg-time">${msg.time}</div>
                </div>
            </div>
        `;
        chatHistEl.insertAdjacentHTML('beforeend', msgHtml);
    });
    
    chatHistEl.scrollTop = chatHistEl.scrollHeight;
}

// Fetches nearby hospitals for a given specialty and appends them as a
// "hospital" message directly inside the chat history (used by both the
// chat flow and the image-analysis flow).
async function fetchHospitalsIntoChat(lat, lon, specialty) {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    try {
        const hospitalResponse = await fetch('/api/hospitals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lat: lat, lon: lon, city: null, specialty: specialty })
        });

        if (!hospitalResponse.ok) throw new Error('Hospital API failed');

        const hospitalData = await hospitalResponse.json();

        chatHistory.push({
            role: 'hospital',
            hospitals: hospitalData.hospitals || [],
            time: time
        });
        renderChatMessages();
    } catch (err) {
        console.error(err);
        // Silently skip hospital suggestions if lookup fails; the bot's
        // medical answer has already been shown to the user.
    }
}

// Builds the hospital card markup used for the inline "hospital" chat
// messages. Reuses the same card look-and-feel as the Hospitals page,
// and the existing booking modal (openBookingModal) - no new booking UI.
function buildHospitalCardsHtml(hospitals) {
    const heading = `
        <div class="hospital-suggestion-heading">
            <span class="heading-icon">🏥</span> Nearby Hospitals Suggested to Visit
        </div>
    `;

    if (!hospitals || hospitals.length === 0) {
        return `
            <div class="hospital-suggestion-container">
                ${heading}
                <div class="empty-state-text">No nearby hospitals found for this specialty.</div>
            </div>
        `;
    }

    const cards = hospitals.map(h => {
        const nameLower = (h.name || '').toLowerCase();
        let icon = '🏥';
        let badgeClass = 'hospital';
        let typeLabel = 'Hospital';

        if (nameLower.includes('clinic')) {
            icon = '🏪';
            badgeClass = 'clinic';
            typeLabel = 'Clinic';
        } else if (nameLower.includes('multispeciality') || nameLower.includes('multi')) {
            icon = '🏨';
            badgeClass = 'multi';
            typeLabel = 'Multispeciality';
        }

        const distanceTag = (h.distance !== undefined && h.distance !== null)
            ? `<span class="hosp-tag">📏 ${h.distance}</span>`
            : '';
        const ratingTag = (h.rating !== undefined && h.rating !== null)
            ? `<span class="hosp-tag">⭐ ${h.rating}</span>`
            : '';

        return `
            <div class="hospital-card">
                <div class="hosp-icon-badge ${badgeClass}">${icon}</div>
                <div class="hosp-info">
                    <div class="hosp-name" title="${h.name}">${h.name}</div>
                    <div class="hosp-addr" title="${h.address}">📍 ${h.address || 'Address unavailable'}</div>
                    <div class="hosp-tags">
                        <span class="hosp-tag">🏷️ ${typeLabel}</span>
                        ${distanceTag}
                        ${ratingTag}
                    </div>
                </div>
                <button class="book-btn" onclick="openBookingModal('${(h.name || '').replace(/'/g, "\\'")}')">Book</button>
            </div>
        `;
    }).join('');

    return `
        <div class="hospital-suggestion-container">
            ${heading}
            <div class="hospital-cards-inline">${cards}</div>
        </div>
    `;
}

function clearConversation() {
    chatHistory = [];
    renderChatMessages();
    const welcome = document.getElementById('welcome-screen');
    if (welcome) welcome.style.display = 'flex';
}

function loadRecentChats() {
    try {
        const saved = localStorage.getItem('recentChats');
        recentChats = saved ? JSON.parse(saved) : [];
        renderRecentChatsList();
    } catch(e) {
        recentChats = [];
    }
}

function saveRecentChat(query) {
    // Check if query already exists, remove it to bring to top
    recentChats = recentChats.filter(q => q !== query);
    recentChats.unshift(query);
    
    // Cap at 6
    if (recentChats.length > 6) {
        recentChats.pop();
    }
    
    localStorage.setItem('recentChats', JSON.stringify(recentChats));
    renderRecentChatsList();
}

function renderRecentChatsList() {
    const listEl = document.getElementById('recent-chats');
    if (!listEl) return;
    
    if (recentChats.length === 0) {
        listEl.innerHTML = '<div class="empty-recent">No conversations yet</div>';
        return;
    }
    
    listEl.innerHTML = '';
    recentChats.forEach(q => {
        const txt = q.length > 32 ? q.substring(0, 32) + '…' : q;
        const html = `
            <div class="recent-item" title="${q}" onclick="sendSuggestion('${q.replace(/'/g, "\\'")}')">
                <span class="recent-dot">●</span>${txt}
            </div>
        `;
        listEl.insertAdjacentHTML('beforeend', html);
    });
}

// ==========================================
// IMAGE ANALYSIS MODULE
// ==========================================
function triggerFileInput() {
    document.getElementById('image-uploader').click();
}

function handleFileSelect(e) {
    const files = e.target.files;
    if (files.length > 0) {
        handleSelectedFile(files[0]);
    }
}

function handleSelectedFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        document.getElementById('image-preview').src = e.target.result;
        document.getElementById('drag-zone').style.display = 'none';
        document.getElementById('preview-zone').style.display = 'flex';
    };
    reader.readAsDataURL(file);
}

function resetImageUpload() {
    document.getElementById('image-uploader').value = '';
    document.getElementById('image-preview').src = '';
    document.getElementById('drag-zone').style.display = 'flex';
    document.getElementById('preview-zone').style.display = 'none';
    document.getElementById('analysis-report-body').innerHTML = '<div class="empty-state-text">Upload and analyze an image to view reports.</div>';
}

async function analyzeSelectedImage() {
    const uploader = document.getElementById('image-uploader');
    if (!uploader || uploader.files.length === 0) return;
    
    const file = uploader.files[0];
    const formData = new FormData();
    formData.append('file', file);
    
    const reportBody = document.getElementById('analysis-report-body');
    reportBody.innerHTML = `
        <div class="shimmer-wrapper">
            <div class="shimmer-line hdr"></div>
            <div class="shimmer-line body-1"></div>
            <div class="shimmer-line body-2"></div>
            <div class="shimmer-line body-3"></div>
            <div class="shimmer-line body-1" style="margin-top: 10px;"></div>
            <div class="shimmer-line body-2"></div>
        </div>
    `;
    
    try {
        const response = await fetch('/api/analyze-image', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) throw new Error('Failed to analyze image');
        
        const data = await response.json();
        
        // Parse the markdown response into styled sections
        const formattedReport = formatMarkdownReport(data.analysis);
        reportBody.innerHTML = formattedReport;
        
        // Save query to Chat History as a mock query
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        chatHistory.push({ role: 'user', content: '📸 Uploaded medical image for analysis', time: time });
        chatHistory.push({ role: 'bot', content: data.analysis, time: time });
        renderChatMessages();

        // Update detected specialty + auto-fetch nearby hospitals into the chat
        if (data.specialty) {
            detectedSpecialty = data.specialty;
            const cleanSpecialty = detectedSpecialty.split('OR')[0].trim();
            const specialtyLabel = document.getElementById('detected-specialty-text');
            if (specialtyLabel) specialtyLabel.innerText = cleanSpecialty;

            if (userLocation.lat !== null && userLocation.lon !== null) {
                await fetchHospitalsIntoChat(userLocation.lat, userLocation.lon, detectedSpecialty);
            }
        }
        
    } catch (err) {
        console.error(err);
        reportBody.innerHTML = `<div class="empty-state-text" style="color:#ef4444">⚠️ Error analyzing image. Make sure Groq key supports llama-4-scout model.</div>`;
    }
}

// Converts Groq markdown report into structured CSS styled divs
function formatMarkdownReport(mdText) {
    let html = '';
    
    // Look for headings: WHAT I SEE, POSSIBLE CONDITION, SEVERITY, RECOMMENDED ACTION, WHICH DOCTOR TO VISIT, IMPORTANT
    const sections = [
        { key: 'WHAT I SEE', label: '🔍 What I See' },
        { key: 'POSSIBLE CONDITION', label: '🩺 Possible Condition' },
        { key: 'SEVERITY', label: '⚠️ Severity' },
        { key: 'RECOMMENDED ACTION', label: '💊 Recommended Action' },
        { key: 'WHICH DOCTOR TO VISIT', label: '👨‍⚕️ Specialist to Visit' },
        { key: 'IMPORTANT', label: '⚕️ Important Note' }
    ];
    
    // Process markdown line-by-line
    const lines = mdText.split('\n');
    let currentSec = null;
    let secContent = [];
    
    const flushSection = () => {
        if (currentSec) {
            let contentStr = secContent.join('\n').trim();
            // Handle severity badges
            if (currentSec.key === 'SEVERITY') {
                let badgeClass = 'severity-mild';
                if (contentStr.toLowerCase().includes('severe')) badgeClass = 'severity-severe';
                else if (contentStr.toLowerCase().includes('moderate')) badgeClass = 'severity-moderate';
                
                contentStr = `<span class="severity-badge ${badgeClass}">${contentStr}</span>`;
            } else {
                // Convert simple bullets
                contentStr = contentStr.replace(/^\*\s(.*)/gm, '• $1');
            }
            
            html += `
                <div class="report-section">
                    <div class="report-label">${currentSec.label}</div>
                    <div class="report-content">${contentStr.replace(/\n/g, '<br>')}</div>
                </div>
            `;
        }
    };
    
    lines.forEach(line => {
        let cleanLine = line.replace(/^[#*\-\s:]+/g, '').trim();
        let matched = false;
        
        for (let sec of sections) {
            if (line.toUpperCase().includes(sec.key)) {
                flushSection();
                currentSec = sec;
                secContent = [];
                matched = true;
                break;
            }
        }
        
        if (!matched && currentSec) {
            if (line.trim() !== '') {
                secContent.push(line);
            }
        }
    });
    
    // Flush remaining
    flushSection();
    
    if (html === '') {
        // Fallback to simple markdown display
        return `<div class="report-content" style="white-space: pre-wrap;">${mdText}</div>`;
    }
    
    return html;
}

// ==========================================
// HOSPITALS & MAP MODULE
// ==========================================
function setSearchMode(mode) {
    searchMode = mode;
    
    const gpsBtn = document.getElementById('mode-gps');
    const manualBtn = document.getElementById('mode-manual');
    const inputGroup = document.getElementById('manual-search-group');
    
    if (mode === 'gps') {
        gpsBtn.classList.add('active');
        manualBtn.classList.remove('active');
        if (inputGroup) inputGroup.style.display = 'none';
    } else {
        gpsBtn.classList.remove('active');
        manualBtn.classList.add('active');
        if (inputGroup) inputGroup.style.display = 'block';
    }
}

function initOrRefreshMap() {
    const mapEl = document.getElementById('hospital-map');
    if (!mapEl) return;
    
    if (!leafMap) {
        // Center on coordinates if available, otherwise general location
        const centerLat = userLocation.lat || 19.0760;
        const centerLon = userLocation.lon || 72.8777;
        
        leafMap = L.map('hospital-map').setView([centerLat, centerLon], 13);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }).addTo(leafMap);
    } else {
        // Redraw sizes
        leafMap.invalidateSize();
        if (userLocation.lat && userLocation.lon) {
            leafMap.setView([userLocation.lat, userLocation.lon], 13);
        }
    }
}

async function triggerHospitalSearch() {
    const countText = document.getElementById('hospitals-count-text');
    const cardsContainer = document.getElementById('hospital-cards-container');
    
    countText.innerText = 'Searching nearby hospitals…';
    cardsContainer.innerHTML = `
        <div class="shimmer-wrapper">
            <div class="shimmer-line body-1"></div>
            <div class="shimmer-line body-2"></div>
            <div class="shimmer-line body-3"></div>
        </div>
    `;
    
    let lat = null;
    let lon = null;
    let city = null;
    
    if (searchMode === 'gps') {
        lat = userLocation.lat;
        lon = userLocation.lon;
        if (!lat || !lon) {
            alert('GPS location not detected yet. Switch to manual search.');
            countText.innerText = 'Search failed';
            cardsContainer.innerHTML = '<div class="empty-state-text">Allow GPS access or write details manually.</div>';
            return;
        }
    } else {
        const cityInput = document.getElementById('city-search-input');
        city = cityInput ? cityInput.value.trim() : '';
        if (!city) {
            alert('Please enter your city or area.');
            countText.innerText = 'Search failed';
            cardsContainer.innerHTML = '<div class="empty-state-text">Enter area to trigger search.</div>';
            return;
        }
    }
    
    try {
        const response = await fetch('/api/hospitals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lat: lat,
                lon: lon,
                city: city,
                specialty: detectedSpecialty
            })
        });
        
        if (!response.ok) throw new Error('Hospital API failed');
        
        const data = await response.json();
        const hospitals = data.hospitals || [];
        
        renderHospitals(hospitals);
        
    } catch (err) {
        console.error(err);
        countText.innerText = 'Error loading hospitals';
        cardsContainer.innerHTML = '<div class="empty-state-text" style="color:#ef4444">⚠️ Error loading hospitals from Nominatim.</div>';
    }
}

function renderHospitals(hospitals) {
    const countText = document.getElementById('hospitals-count-text');
    const cardsContainer = document.getElementById('hospital-cards-container');
    
    countText.innerText = `Found ${hospitals.length} results near you`;
    cardsContainer.innerHTML = '';
    
    // Clear old map markers
    leafMarkers.forEach(m => leafMap.removeLayer(m));
    leafMarkers = [];
    
    if (hospitals.length === 0) {
        cardsContainer.innerHTML = '<div class="empty-state-text">No matching hospitals found. Try widening search details.</div>';
        return;
    }
    
    // Add user position marker if GPS is active
    if (searchMode === 'gps' && userLocation.lat && userLocation.lon) {
        const userMarker = L.marker([userLocation.lat, userLocation.lon], {
            icon: L.divIcon({
                className: 'user-location-marker',
                html: '<div style="background-color:#3b82f6;width:14px;height:14px;border-radius:50%;border:2.5px solid white;box-shadow:0 0 8px #3b82f6;"></div>',
                iconSize: [14, 14]
            })
        }).addTo(leafMap).bindPopup('📍 You are here');
        leafMarkers.push(userMarker);
    }
    
    hospitals.forEach((h, index) => {
        const nameLower = h.name.toLowerCase();
        let icon = '🏥';
        let badgeClass = 'hospital';
        let typeLabel = 'Hospital';
        
        if (nameLower.includes('clinic')) {
            icon = '🏪';
            badgeClass = 'clinic';
            typeLabel = 'Clinic';
        } else if (nameLower.includes('multispeciality') || nameLower.includes('multi')) {
            icon = '🏨';
            badgeClass = 'multi';
            typeLabel = 'Multispeciality';
        }
        
        // Add marker on Leaflet map
        const hospitalMarker = L.marker([h.lat, h.lon]).addTo(leafMap)
            .bindPopup(`<b>${h.name}</b><br><span style="font-size:11px">${h.address}</span>`);
        leafMarkers.push(hospitalMarker);
        
        // Render html list item
        const cardHtml = `
            <div class="hospital-card">
                <div class="hosp-icon-badge ${badgeClass}">${icon}</div>
                <div class="hosp-info">
                    <div class="hosp-name" title="${h.name}">${h.name}</div>
                    <div class="hosp-addr" title="${h.address}">📍 ${h.address}</div>
                    <div class="hosp-tags">
                        <span class="hosp-tag">🏷️ ${typeLabel}</span>
                    </div>
                </div>
                <button class="book-btn" onclick="openBookingModal('${h.name.replace(/'/g, "\\'")}')">Book</button>
            </div>
        `;
        cardsContainer.insertAdjacentHTML('beforeend', cardHtml);
    });
    
    // Zoom map to fit markers
    if (leafMarkers.length > 0) {
        const group = new L.featureGroup(leafMarkers);
        leafMap.fitBounds(group.getBounds().pad(0.15));
    }
}

// ==========================================
// APPOINTMENTS & BOOKINGS MODULE
// ==========================================
async function loadAppointments() {
    const container = document.getElementById('appointments-cards-container');
    container.innerHTML = `
        <div class="shimmer-wrapper">
            <div class="shimmer-line body-1"></div>
            <div class="shimmer-line body-2"></div>
        </div>
    `;
    
    try {
        const response = await fetch('/api/appointments');
        if (!response.ok) throw new Error('Failed to load appointments');
        
        const data = await response.json();
        const appointments = data.appointments || [];
        
        renderAppointments(appointments);
        
    } catch (err) {
        console.error(err);
        container.innerHTML = '<div class="empty-state-text" style="color:#ef4444">⚠️ Failed to read appointments list.</div>';
    }
}

function renderAppointments(appointments) {
    const container = document.getElementById('appointments-cards-container');
    container.innerHTML = '';
    
    if (appointments.length === 0) {
        container.innerHTML = '<div class="empty-state-text" style="grid-column: 1/-1;">No appointments found. Use the "Find Hospitals" page to book one!</div>';
        return;
    }
    
    appointments.forEach(app => {
        const cardHtml = `
            <div class="appointment-card">
                <div class="appt-header">
                    <span class="appt-title" title="${app.Hospital}">${app.Hospital}</span>
                    <span class="appt-status-badge">Confirmed</span>
                </div>
                <div class="appt-body">
                    <div class="appt-row">
                        <span class="appt-lbl">Patient Name</span>
                        <span class="appt-val">${app.Name}</span>
                    </div>
                    <div class="appt-row">
                        <span class="appt-lbl">Age</span>
                        <span class="appt-val">${app.Age} yrs</span>
                    </div>
                    <div class="appt-row">
                        <span class="appt-lbl">Contact Phone</span>
                        <span class="appt-val">${app.Phone}</span>
                    </div>
                    <div class="appt-row">
                        <span class="appt-lbl">Schedule Date</span>
                        <span class="appt-val" style="color:#3b82f6;">📅 ${app.Date}</span>
                    </div>
                </div>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', cardHtml);
    });
}

// Booking Modal Controls
function openBookingModal(hospitalName) {
    selectedHospitalForBooking = hospitalName;
    document.getElementById('modal-hospital-name').innerText = hospitalName;
    
    // Set default date to tomorrow
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    const dateInput = document.getElementById('booking-date');
    if (dateInput) {
        dateInput.value = tomorrow.toISOString().split('T')[0];
        dateInput.min = new Date().toISOString().split('T')[0]; // Can't book in past
    }
    
    document.getElementById('booking-modal-overlay').classList.add('active');
}

function closeBookingModal() {
    document.getElementById('booking-modal-overlay').classList.remove('active');
    document.getElementById('booking-form').reset();
    selectedHospitalForBooking = null;
}

async function confirmBooking(event) {
    event.preventDefault();
    if (!selectedHospitalForBooking) return;
    
    const name = document.getElementById('booking-name').value.trim();
    const age = parseInt(document.getElementById('booking-age').value);
    const phone = document.getElementById('booking-phone').value.trim();
    const date = document.getElementById('booking-date').value;
    
    if (!name || !phone || !date) {
        alert('Please fill out all fields.');
        return;
    }
    
    try {
        const response = await fetch('/api/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                hospital: selectedHospitalForBooking,
                name: name,
                phone: phone,
                age: age,
                date: date
            })
        });
        
        if (!response.ok) throw new Error('API booking failed');
        
        alert('🎉 Appointment booked successfully!');
        closeBookingModal();
        switchView('appointments');
        
    } catch(err) {
        console.error(err);
        alert('⚠️ Booking failed. Try again.');
    }
}