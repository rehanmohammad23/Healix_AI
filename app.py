import streamlit as st
from src.retrieval.rag_chain import build_rag_chain, ask
from datetime import datetime
import base64
import requests
import csv
import os
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

st.set_page_config(
    page_title="HEALIX AI",
    page_icon="🧬",
    layout="centered"
)

# Load image
def get_image_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

try:
    img_base64 = get_image_base64("HEALIX.png")
    img_tag = f'<img src="data:image/png;base64,{img_base64}" class="healix-logo"/>'
except:
    img_tag = '<div style="font-size:4em;">🧬</div>'

# Analyze medical image
def analyze_medical_image(image_bytes, mime_type="image/jpeg"):
    try:
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_b64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": """You are HEALIX AI — an expert medical image analyzer.
Analyze this medical image carefully and provide:

🔍 WHAT I SEE:
(Describe what is visible in the image clearly)

🩺 POSSIBLE CONDITION:
(What medical condition this might be)

⚠️ SEVERITY:
(Mild / Moderate / Severe — based on what you see)

💊 RECOMMENDED ACTION:
(What the person should do)

👨‍⚕️ WHICH DOCTOR TO VISIT:
(Specific specialist to consult)

⚕️ IMPORTANT:
This is an AI analysis only. Please consult a qualified doctor for proper diagnosis.

Be clear, helpful and accurate."""
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Image analysis failed: {str(e)}"

# Get area from coordinates
def get_city_from_coords(lat, lon):
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1}
        headers = {"User-Agent": "HealixAI/1.0"}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        address = data.get("address", {})
        area = (
            address.get("suburb") or
            address.get("neighbourhood") or
            address.get("quarter") or
            address.get("village") or
            address.get("town") or
            address.get("city") or ""
        )
        city = address.get("city") or address.get("town") or ""
        if area and city and area != city:
            return f"{area}, {city}"
        return city or area
    except:
        return ""

# Detect specialty
def detect_specialty(question):
    question = question.lower()
    if any(w in question for w in ["heart", "cardiac", "chest pain", "blood pressure", "hypertension", "palpitation", "angina"]):
        return "cardiology hospital OR cardiology clinic OR multispeciality hospital"
    elif any(w in question for w in ["skin", "rash", "acne", "eczema", "dermatitis", "psoriasis", "itching", "pimple", "fungal", "wound", "burn", "allergy", "hives", "scar", "pigmentation", "dark spots", "hair loss", "dandruff"]):
        return "dermatology clinic OR skin hospital OR multispeciality hospital"
    elif any(w in question for w in ["bone", "joint", "fracture", "arthritis", "ortho", "spine", "back pain", "knee", "shoulder"]):
        return "orthopedic hospital OR orthopedic clinic OR multispeciality hospital"
    elif any(w in question for w in ["brain", "neurology", "headache", "migraine", "seizure", "stroke", "paralysis", "nerve", "vertigo"]):
        return "neurology hospital OR neurology clinic OR multispeciality hospital"
    elif any(w in question for w in ["eye", "vision", "cataract", "glaucoma", "retina", "blind", "cornea"]):
        return "eye hospital OR eye clinic OR ophthalmology clinic"
    elif any(w in question for w in ["teeth", "tooth", "dental", "gum", "cavity", "braces", "root canal"]):
        return "dental clinic OR dentist OR dental hospital"
    elif any(w in question for w in ["child", "baby", "infant", "pediatric", "kid", "newborn", "toddler"]):
        return "children hospital OR pediatric clinic OR multispeciality hospital"
    elif any(w in question for w in ["mental", "depression", "anxiety", "psychiatric", "psychology", "stress", "bipolar", "ocd"]):
        return "psychiatric hospital OR mental health clinic OR psychiatry clinic"
    elif any(w in question for w in ["kidney", "renal", "dialysis", "urine", "urinary", "bladder"]):
        return "nephrology hospital OR kidney clinic OR urology clinic"
    elif any(w in question for w in ["lung", "breathing", "asthma", "pulmonary", "respiratory", "cough", "tuberculosis"]):
        return "pulmonology hospital OR chest clinic OR respiratory clinic"
    elif any(w in question for w in ["cancer", "tumor", "oncology", "chemotherapy", "radiation", "biopsy"]):
        return "cancer hospital OR oncology clinic OR multispeciality hospital"
    elif any(w in question for w in ["stomach", "digestion", "gastro", "liver", "intestine", "bowel", "diarrhea", "ulcer"]):
        return "gastroenterology hospital OR gastro clinic OR multispeciality hospital"
    elif any(w in question for w in ["women", "pregnancy", "gynecology", "uterus", "ovary", "periods", "pcos", "fertility"]):
        return "gynecology hospital OR women clinic OR maternity hospital"
    elif any(w in question for w in ["diabetes", "thyroid", "hormone", "endocrine", "insulin", "blood sugar"]):
        return "endocrinology hospital OR diabetes clinic OR multispeciality hospital"
    elif any(w in question for w in ["ear", "hearing", "ent", "nose", "throat", "tonsil", "sinusitis"]):
        return "ENT clinic OR ear nose throat clinic OR multispeciality hospital"
    elif any(w in question for w in ["fever", "cold", "flu", "infection", "viral", "bacterial", "typhoid", "malaria"]):
        return "general hospital OR medical clinic OR multispeciality hospital"
    elif any(w in question for w in ["blood", "anemia", "hemoglobin", "platelet"]):
        return "hematology clinic OR multispeciality hospital OR general hospital"
    else:
        return "multispeciality hospital OR general hospital OR medical clinic"

# Search hospitals by GPS
def search_hospitals_by_coords(lat, lon, specialty):
    try:
        all_hospitals = []
        seen_names = set()
        headers = {"User-Agent": "HealixAI/1.0"}
        specialty_parts = [s.strip() for s in specialty.split("OR")]
        search_terms = specialty_parts + [
            "multispeciality hospital", "hospital", "clinic", "medical centre"
        ]
        for term in search_terms:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": term, "format": "json", "limit": 5, "addressdetails": 1,
                "viewbox": f"{lon-0.1},{lat+0.1},{lon+0.1},{lat-0.1}", "bounded": 1
            }
            try:
                response = requests.get(url, params=params, headers=headers, timeout=10)
                results = response.json()
                for r in results:
                    name = r.get("display_name", "").split(",")[0]
                    if name not in seen_names:
                        seen_names.add(name)
                        address = ", ".join(r.get("display_name", "").split(",")[1:4])
                        hlat = float(r["lat"])
                        hlon = float(r["lon"])
                        all_hospitals.append({"name": name, "address": address, "lat": hlat, "lon": hlon})
            except:
                continue
            if len(all_hospitals) >= 8:
                break
        return all_hospitals[:8]
    except:
        return []

# Search hospitals by city
def search_hospitals_by_city(city, specialty):
    try:
        all_hospitals = []
        seen_names = set()
        headers = {"User-Agent": "HealixAI/1.0"}
        specialty_parts = [s.strip() for s in specialty.split("OR")]
        search_terms = []
        for part in specialty_parts:
            search_terms.append(f"{part} in {city}")
        search_terms += [
            f"multispeciality hospital in {city}",
            f"hospital in {city}",
            f"clinic in {city}",
            f"medical centre in {city}",
        ]
        for term in search_terms:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": term, "format": "json", "limit": 5, "addressdetails": 1}
            try:
                response = requests.get(url, params=params, headers=headers, timeout=10)
                results = response.json()
                for r in results:
                    name = r.get("display_name", "").split(",")[0]
                    if name not in seen_names:
                        seen_names.add(name)
                        address = ", ".join(r.get("display_name", "").split(",")[1:4])
                        lat = float(r["lat"])
                        lon = float(r["lon"])
                        all_hospitals.append({"name": name, "address": address, "lat": lat, "lon": lon})
            except:
                continue
            if len(all_hospitals) >= 8:
                break
        return all_hospitals[:8]
    except:
        return []

# Save booking
def save_booking(hospital_name, name, phone, age, date):
    file = "bookings.csv"
    exists = os.path.exists(file)
    with open(file, "a", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["Hospital", "Name", "Phone", "Age", "Date", "Booked At"])
        writer.writerow([hospital_name, name, phone, age, date,
                        datetime.now().strftime("%Y-%m-%d %H:%M")])

# Theme
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = True

if st.session_state.dark_mode:
    bg_color = "#0a0a1a"
    bg_secondary = "#0d0d2b"
    text_color = "#e0e0ff"
    user_bg = "linear-gradient(135deg, #6a0dad, #9b30ff)"
    bot_bg = "#0d1b2a"
    border_color = "#00e5ff"
    sidebar_bg = "#0a0a1a"
    accent = "#00e5ff"
    glow = "0 0 15px #00e5ff, 0 0 30px #6a0dad"
    header_gradient = "linear-gradient(90deg, #00e5ff, #9b30ff)"
    sub_color = "#a0a0cc"
    button_bg = "#1a0a3a"
    button_border = "#00e5ff"
else:
    bg_color = "#f0f0ff"
    bg_secondary = "#e8e8ff"
    text_color = "#0a0a2a"
    user_bg = "linear-gradient(135deg, #6a0dad, #9b30ff)"
    bot_bg = "#dde8ff"
    border_color = "#6a0dad"
    sidebar_bg = "#e0e0ff"
    accent = "#6a0dad"
    glow = "0 0 10px #9b30ff"
    header_gradient = "linear-gradient(90deg, #6a0dad, #00bcd4)"
    sub_color = "#444477"
    button_bg = "#d0d0ff"
    button_border = "#6a0dad"

st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Rajdhani:wght@400;600&display=swap');
    .stApp {{
        background-color: {bg_color};
        background-image: radial-gradient(ellipse at top, {bg_secondary} 0%, {bg_color} 70%);
        color: {text_color};
        font-family: 'Rajdhani', sans-serif;
    }}
    .healix-logo {{
        width: 120px; height: 120px; border-radius: 50%;
        animation: rotateLogo 8s linear infinite;
        box-shadow: 0 0 30px #00e5ff, 0 0 60px #6a0dad;
        display: block; margin: 0 auto;
    }}
    @keyframes rotateLogo {{
        0% {{ transform: rotate(0deg); }}
        100% {{ transform: rotate(360deg); }}
    }}
    .healix-header {{ text-align: center; padding: 20px 0 10px 0; }}
    .healix-title {{
        font-family: 'Orbitron', monospace; font-size: 3em; font-weight: 700;
        background: {header_gradient}; -webkit-background-clip: text;
        -webkit-text-fill-color: transparent; letter-spacing: 4px; margin: 10px 0 0 0;
    }}
    .healix-subtitle {{ color: {sub_color}; font-size: 1em; letter-spacing: 2px; margin-top: 5px; }}
    .healix-divider {{ border: none; height: 1px; background: {header_gradient}; box-shadow: {glow}; margin: 15px 0; }}
    .message-container {{ display: flex; flex-direction: column; gap: 4px; margin: 10px 0; }}
    .user-message {{
        background: {user_bg}; color: white; padding: 12px 18px;
        border-radius: 18px 18px 4px 18px; margin-left: auto; max-width: 80%;
        font-size: 15px; line-height: 1.6; box-shadow: 0 0 10px #9b30ff88;
    }}
    .bot-message {{
        background: {bot_bg}; color: {text_color}; padding: 12px 18px;
        border-radius: 18px 18px 18px 4px; margin-right: auto; max-width: 80%;
        font-size: 15px; line-height: 1.6; border: 1px solid {border_color};
        box-shadow: 0 0 12px {border_color}55;
    }}
    .hospital-card {{
        background: {bot_bg}; border: 1px solid {border_color};
        border-radius: 12px; padding: 15px; margin: 8px 0;
        box-shadow: 0 0 10px {border_color}44;
    }}
    .image-analysis-card {{
        background: {bot_bg}; border: 1px solid {accent};
        border-radius: 12px; padding: 15px; margin: 10px 0;
        box-shadow: 0 0 15px {accent}44;
    }}
    .upload-section {{
        border: 2px dashed {accent}; border-radius: 12px;
        padding: 20px; text-align: center; margin: 10px 0;
        background: {accent}11;
    }}
    .specialty-badge {{
        display: inline-block; background: {accent}22;
        border: 1px solid {accent}; border-radius: 20px;
        padding: 4px 12px; font-size: 12px; color: {accent}; margin-bottom: 10px;
    }}
    .location-badge {{
        display: inline-block; background: #00ff8822;
        border: 1px solid #00ff88; border-radius: 20px;
        padding: 4px 12px; font-size: 12px; color: #00ff88;
        margin-bottom: 10px; margin-left: 8px;
    }}
    .timestamp {{ font-size: 11px; opacity: 0.5; margin: 2px 4px; letter-spacing: 1px; }}
    .user-timestamp {{ text-align: right; color: {sub_color}; }}
    .bot-timestamp {{ text-align: left; color: {sub_color}; }}
    section[data-testid="stSidebar"] {{
        background-color: {sidebar_bg} !important;
        background-image: radial-gradient(ellipse at top, {bg_secondary} 0%, {sidebar_bg} 100%) !important;
        border-right: 1px solid {border_color};
    }}
    .stButton > button {{
        background: {button_bg} !important; color: {accent} !important;
        border: 1px solid {button_border} !important; border-radius: 8px !important;
        font-family: 'Rajdhani', sans-serif !important; font-size: 14px !important;
        letter-spacing: 1px !important; transition: all 0.3s ease !important;
    }}
    .stButton > button:hover {{ box-shadow: {glow} !important; transform: scale(1.02) !important; }}
    p, label, div, span, li {{ color: {text_color}; }}
    h1, h2, h3 {{ color: {accent} !important; font-family: 'Orbitron', monospace !important; letter-spacing: 2px; }}
    ::-webkit-scrollbar {{ width: 6px; }}
    ::-webkit-scrollbar-track {{ background: {bg_color}; }}
    ::-webkit-scrollbar-thumb {{ background: {accent}; border-radius: 3px; }}
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "show_hospitals" not in st.session_state:
    st.session_state.show_hospitals = False
if "hospitals" not in st.session_state:
    st.session_state.hospitals = []
if "booking_hospital" not in st.session_state:
    st.session_state.booking_hospital = None
if "detected_specialty" not in st.session_state:
    st.session_state.detected_specialty = "multispeciality hospital OR general hospital"
if "user_lat" not in st.session_state:
    st.session_state.user_lat = None
if "user_lon" not in st.session_state:
    st.session_state.user_lon = None
if "user_location" not in st.session_state:
    st.session_state.user_location = ""
if "city" not in st.session_state:
    st.session_state.city = ""

# Get GPS
location = get_geolocation()
if location:
    try:
        lat = location["coords"]["latitude"]
        lon = location["coords"]["longitude"]
        if st.session_state.user_lat != lat:
            st.session_state.user_lat = lat
            st.session_state.user_lon = lon
            detected = get_city_from_coords(lat, lon)
            st.session_state.user_location = detected
            st.session_state.city = detected
    except:
        pass

# Sidebar
with st.sidebar:
    st.markdown(f"<h2 style='color:{accent};font-family:Orbitron;font-size:1em;letter-spacing:2px;'>⚙️ CONTROLS</h2>", unsafe_allow_html=True)
    mode_label = "☀️ Light Mode" if st.session_state.dark_mode else "🌙 Dark Mode"
    if st.button(mode_label, use_container_width=True):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()
    st.markdown(f"<hr style='border-color:{border_color};'>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color:{accent};font-family:Orbitron;font-size:1em;letter-spacing:2px;'>📍 LOCATION</h2>", unsafe_allow_html=True)
    if st.session_state.user_location:
        st.markdown(f"<p style='color:#00ff88;font-size:13px;'>📍 {st.session_state.user_location}</p>", unsafe_allow_html=True)
        st.markdown(f"<p style='color:{sub_color};font-size:11px;'>✅ GPS detected</p>", unsafe_allow_html=True)
    else:
        st.markdown(f"<p style='color:{sub_color};font-size:13px;'>📍 Detecting location...</p>", unsafe_allow_html=True)
    st.markdown(f"<hr style='border-color:{border_color};'>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color:{accent};font-family:Orbitron;font-size:1em;letter-spacing:2px;'>💬 HISTORY</h2>", unsafe_allow_html=True)
    if "messages" in st.session_state and st.session_state.messages:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                truncated = msg["content"][:35] + "..." if len(msg["content"]) > 35 else msg["content"]
                st.markdown(f"<p style='color:{sub_color};font-size:13px;'>🔹 {truncated}</p>", unsafe_allow_html=True)
    else:
        st.markdown(f"<p style='color:{sub_color};font-size:13px;'>No history yet</p>", unsafe_allow_html=True)
    st.markdown(f"<hr style='border-color:{border_color};'>", unsafe_allow_html=True)
    if st.button("🗑️ Clear History", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.markdown(f"<hr style='border-color:{border_color};'>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color:{accent};font-family:Orbitron;font-size:1em;letter-spacing:2px;'>📚 KNOWLEDGE</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{sub_color};font-size:13px;'>🧬 6 Medical Books Loaded</p>", unsafe_allow_html=True)
    st.markdown(f"<hr style='border-color:{border_color};'>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{sub_color};font-size:11px;text-align:center;'>HEALIX AI • Llama 3 + ChromaDB</p>", unsafe_allow_html=True)

# Header
st.markdown(f"""
    <div class='healix-header'>
        {img_tag}
        <p class='healix-title'>HEALIX AI</p>
        <p class='healix-subtitle'>⚡ AI-POWERED MEDICAL ASSISTANT ⚡</p>
    </div>
    <hr class='healix-divider'>
""", unsafe_allow_html=True)

# Load chain
@st.cache_resource(show_spinner="🧬 Initializing HEALIX AI...")
def load_chain():
    return build_rag_chain()

chain = load_chain()

# Welcome
if not st.session_state.messages:
    location_text = f"📍 <b style='color:#00ff88;'>{st.session_state.user_location}</b>" if st.session_state.user_location else "📍 Allow location access for nearby hospitals"
    st.markdown(f"""
        <div style='text-align:center;margin:40px auto;'>
            <h1 style='font-family:Orbitron;font-size:2.8em;background:{header_gradient};
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;
            letter-spacing:6px;margin-bottom:10px;'>WELCOME</h1>
            <p style='font-size:1.4em;color:{sub_color};margin-top:10px;letter-spacing:1px;'>
                I'm <span style='color:{accent};font-weight:bold;font-family:Orbitron;font-size:1.1em;'>HEALIX</span> — How can I help you?
            </p>
            <p style='font-size:0.9em;color:{sub_color};opacity:0.8;margin-top:15px;'>{location_text}</p>
            <p style='font-size:0.85em;color:{sub_color};opacity:0.6;margin-top:8px;'>
                💬 Ask a question OR 📸 Upload an image for analysis
            </p>
        </div>
    """, unsafe_allow_html=True)

# ---- IMAGE UPLOAD SECTION ----
uploaded_file = st.file_uploader(
    "📸",
    type=["jpg", "jpeg", "png", "webp"],
    label_visibility="visible"
)

if uploaded_file:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.image(uploaded_file, caption="Uploaded Image", use_container_width=True)
    with col2:
        if st.button("🔬 Analyze Image", use_container_width=True):
            with st.spinner("🔬 Analyzing your image..."):
                image_bytes = uploaded_file.read()
                mime_type = f"image/{uploaded_file.name.split('.')[-1].lower()}"
                if mime_type == "image/jpg":
                    mime_type = "image/jpeg"
                analysis = analyze_medical_image(image_bytes, mime_type)

            st.markdown(f"""
                <div class='image-analysis-card'>
                    <h4 style='color:{accent};margin:0 0 10px 0;'>🔬 AI Image Analysis Result</h4>
                    <p style='color:{text_color};white-space:pre-wrap;font-size:14px;'>{analysis}</p>
                </div>
            """, unsafe_allow_html=True)

            # Auto detect specialty from analysis
            specialty = detect_specialty(analysis)
            st.session_state.detected_specialty = specialty
            st.session_state.show_hospitals = True
            st.session_state.hospitals = []

            # Add to chat history
            now = datetime.now().strftime("%I:%M %p")
            st.session_state.messages.append({
                "role": "user",
                "content": "📸 Uploaded medical image for analysis",
                "time": now
            })
            st.session_state.messages.append({
                "role": "assistant",
                "content": analysis,
                "time": now,
                "sources": []
            })

st.markdown(f"<hr style='border-color:{border_color};margin:15px 0;'>", unsafe_allow_html=True)

# Display chat history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(f"""
            <div class='message-container'>
                <div class='user-message'>{msg["content"]}</div>
                <div class='timestamp user-timestamp'>🕐 {msg.get("time", "")}</div>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
            <div class='message-container'>
                <div class='bot-message'>🤖 {msg["content"]}</div>
                <div class='timestamp bot-timestamp'>🕐 {msg.get("time", "")}</div>
            </div>
        """, unsafe_allow_html=True)
        if msg.get("sources"):
            with st.expander("📚 View Sources"):
                for s in msg["sources"]:
                    st.markdown(f"<p style='color:{accent};'>▸ {s}</p>", unsafe_allow_html=True)

# Hospital section
if st.session_state.show_hospitals:
    st.markdown(f"<hr style='border-color:{border_color};'>", unsafe_allow_html=True)
    specialty = st.session_state.detected_specialty
    first_specialty = specialty.split("OR")[0].strip().title()

    st.markdown(f"""
        <div style='text-align:center;margin:10px 0;'>
            <h3 style='color:{accent};'>🏥 Nearby Hospitals & Clinics</h3>
            <div class='specialty-badge'>🎯 {first_specialty}</div>
            {f"<div class='location-badge'>📍 {st.session_state.user_location}</div>" if st.session_state.user_location else ""}
        </div>
    """, unsafe_allow_html=True)

    use_gps = st.session_state.user_lat is not None
    if use_gps:
        st.success(f"📍 GPS detected: **{st.session_state.user_location}**")
        search_mode = st.radio(
            "Search using:",
            ["📍 My exact GPS location", "🏙️ Enter area manually"],
            horizontal=True
        )
    else:
        st.warning("⚠️ Allow location in browser OR enter your area manually below.")
        search_mode = "🏙️ Enter area manually"

    city_input = ""
    if search_mode == "🏙️ Enter area manually":
        city_input = st.text_input(
            "📍 Enter your area or city:",
            placeholder="e.g. Medchal, Kukatpally, Hyderabad...",
            value=st.session_state.city
        )

    if st.button("🔍 Search Hospitals & Clinics", use_container_width=True):
        with st.spinner("🔍 Searching nearby hospitals & clinics..."):
            if search_mode == "📍 My exact GPS location" and use_gps:
                hospitals = search_hospitals_by_coords(
                    st.session_state.user_lat,
                    st.session_state.user_lon,
                    specialty
                )
            else:
                city = city_input or st.session_state.city
                st.session_state.city = city
                hospitals = search_hospitals_by_city(city, specialty)
            st.session_state.hospitals = hospitals

    if st.session_state.hospitals:
        st.markdown(f"<p style='color:{accent};margin:10px 0;'>✅ Found <b>{len(st.session_state.hospitals)}</b> hospitals & clinics nearby:</p>", unsafe_allow_html=True)

        if use_gps and search_mode == "📍 My exact GPS location":
            m = folium.Map(location=[st.session_state.user_lat, st.session_state.user_lon], zoom_start=14)
            folium.Marker(
                [st.session_state.user_lat, st.session_state.user_lon],
                popup="You are here", tooltip="📍 Your Location",
                icon=folium.Icon(color="blue", icon="user")
            ).add_to(m)
        else:
            first = st.session_state.hospitals[0]
            m = folium.Map(location=[first["lat"], first["lon"]], zoom_start=13)

        for h in st.session_state.hospitals:
            folium.Marker(
                [h["lat"], h["lon"]], popup=h["name"], tooltip=h["name"],
                icon=folium.Icon(color="red", icon="plus-sign")
            ).add_to(m)
        st_folium(m, width=700, height=400)

        for i, h in enumerate(st.session_state.hospitals):
            name_lower = h["name"].lower()
            if "clinic" in name_lower:
                icon = "🏪"; type_label = "Clinic"
            elif "multispeciality" in name_lower or "multi" in name_lower:
                icon = "🏨"; type_label = "Multispeciality Hospital"
            else:
                icon = "🏥"; type_label = "Hospital"

            st.markdown(f"""
                <div class='hospital-card'>
                    <h4 style='color:{accent};margin:0;'>{icon} {h['name']}</h4>
                    <p style='color:{sub_color};margin:5px 0;font-size:13px;'>📍 {h['address']}</p>
                    <p style='color:{sub_color};margin:0;font-size:12px;'>
                        🏷️ Type: <b>{type_label}</b> &nbsp;|&nbsp;
                        🎯 For: <b>{first_specialty}</b>
                    </p>
                </div>
            """, unsafe_allow_html=True)
            if st.button(f"📅 Book — {h['name'][:35]}", key=f"book_{i}"):
                st.session_state.booking_hospital = h["name"]
                st.rerun()

    elif len(st.session_state.hospitals) == 0 and st.session_state.city:
        st.warning("⚠️ No results found. Try your district or nearest big city!")

    if st.session_state.booking_hospital:
        st.markdown(f"<hr style='border-color:{border_color};'>", unsafe_allow_html=True)
        st.markdown(f"""
            <div style='text-align:center;'>
                <h3 style='color:{accent};'>📋 Book Appointment</h3>
                <p style='color:{sub_color};'>🏥 <b style='color:{accent};'>{st.session_state.booking_hospital}</b></p>
            </div>
        """, unsafe_allow_html=True)

        name = st.text_input("👤 Full Name:", placeholder="Enter your full name")
        phone = st.text_input("📞 Phone Number:", placeholder="Enter your phone number")
        age = st.number_input("🎂 Age:", min_value=1, max_value=120, value=25)
        date = st.date_input("📅 Preferred Date:", min_value=datetime.today())

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Confirm Booking", use_container_width=True):
                if name and phone:
                    save_booking(st.session_state.booking_hospital, name, phone, age, str(date))
                    st.success("✅ Appointment Booked Successfully!")
                    st.markdown(f"""
                        <div class='hospital-card'>
                            <h4 style='color:{accent};'>🎉 Booking Confirmed!</h4>
                            <p style='color:{sub_color};'>🏥 <b>{st.session_state.booking_hospital}</b></p>
                            <p style='color:{sub_color};'>👤 Name: <b>{name}</b></p>
                            <p style='color:{sub_color};'>📞 Phone: <b>{phone}</b></p>
                            <p style='color:{sub_color};'>🎂 Age: <b>{age}</b></p>
                            <p style='color:{sub_color};'>📅 Date: <b>{date}</b></p>
                        </div>
                    """, unsafe_allow_html=True)
                    st.balloons()
                    st.session_state.booking_hospital = None
                else:
                    st.error("⚠️ Please fill in Name and Phone!")
        with col2:
            if st.button("❌ Cancel", use_container_width=True):
                st.session_state.booking_hospital = None
                st.rerun()

# Chat input
if prompt := st.chat_input("⚡ Ask HEALIX AI anything medical..."):
    now = datetime.now().strftime("%I:%M %p")
    st.session_state.messages.append({"role": "user", "content": prompt, "time": now})

    with st.spinner("🔍 Scanning medical knowledge base..."):
        answer, sources = ask(chain, prompt)

    st.session_state.messages.append({
        "role": "assistant", "content": answer,
        "time": now, "sources": sources
    })

    st.session_state.detected_specialty = detect_specialty(prompt)
    st.session_state.show_hospitals = True
    st.session_state.hospitals = []
    st.session_state.booking_hospital = None
    st.rerun()