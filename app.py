import streamlit as st
from src.retrieval.rag_chain import build_rag_chain, ask
from datetime import datetime
import base64, requests, csv, os
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

st.set_page_config(page_title="Healix AI", page_icon="🩺", layout="wide", initial_sidebar_state="expanded")

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_image_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def analyze_medical_image(image_bytes, mime_type="image/jpeg"):
    try:
        r = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"}},
                {"type":"text","text":(
                    "You are HEALIX AI — an expert medical image analyzer.\n"
                    "Analyze this medical image carefully and provide:\n\n"
                    " WHAT I SEE:\n(Describe what is visible)\n\n"
                    " POSSIBLE CONDITION:\n(What medical condition this might be)\n\n"
                    " SEVERITY:\n(Mild / Moderate / Severe)\n\n"
                    " RECOMMENDED ACTION:\n(What the person should do)\n\n"
                    " WHICH DOCTOR TO VISIT:\n(Specific specialist)\n\n"
                    " IMPORTANT:\nThis is AI analysis only. Consult a qualified doctor."
                )}
            ]}],
            max_tokens=1000
        )
        return r.choices[0].message.content
    except Exception as e:
        return f"Image analysis failed: {str(e)}"

def get_city_from_coords(lat, lon):
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse",
            params={"lat":lat,"lon":lon,"format":"json","addressdetails":1},
            headers={"User-Agent":"HealixAI/1.0"}, timeout=10)
        a = r.json().get("address",{})
        area = a.get("suburb") or a.get("neighbourhood") or a.get("town") or ""
        city = a.get("city") or a.get("town") or ""
        return f"{area}, {city}" if area and city and area != city else (city or area)
    except: return ""

def detect_specialty(q):
    q = q.lower()
    rules = [
        (["heart","cardiac","chest pain","blood pressure","hypertension","palpitation"], "cardiology hospital OR cardiology clinic OR multispeciality hospital"),
        (["skin","rash","acne","eczema","dermatitis","psoriasis","itching","pimple","fungal","wound","burn","allergy","hives","scar","pigmentation","hair loss","dandruff"], "dermatology clinic OR skin hospital OR multispeciality hospital"),
        (["bone","joint","fracture","arthritis","ortho","spine","back pain","knee","shoulder"], "orthopedic hospital OR orthopedic clinic OR multispeciality hospital"),
        (["brain","neurology","headache","migraine","seizure","stroke","paralysis","nerve","vertigo"], "neurology hospital OR neurology clinic OR multispeciality hospital"),
        (["eye","vision","cataract","glaucoma","retina","blind","cornea"], "eye hospital OR eye clinic OR ophthalmology clinic"),
        (["teeth","tooth","dental","gum","cavity","braces","root canal"], "dental clinic OR dentist OR dental hospital"),
        (["child","baby","infant","pediatric","kid","newborn","toddler"], "children hospital OR pediatric clinic OR multispeciality hospital"),
        (["mental","depression","anxiety","psychiatric","psychology","stress","bipolar","ocd"], "psychiatric hospital OR mental health clinic OR psychiatry clinic"),
        (["kidney","renal","dialysis","urine","urinary","bladder"], "nephrology hospital OR kidney clinic OR urology clinic"),
        (["lung","breathing","asthma","pulmonary","respiratory","cough","tuberculosis"], "pulmonology hospital OR chest clinic OR respiratory clinic"),
        (["cancer","tumor","oncology","chemotherapy","radiation","biopsy"], "cancer hospital OR oncology clinic OR multispeciality hospital"),
        (["stomach","digestion","gastro","liver","intestine","bowel","diarrhea","ulcer"], "gastroenterology hospital OR gastro clinic OR multispeciality hospital"),
        (["women","pregnancy","gynecology","uterus","ovary","periods","pcos","fertility"], "gynecology hospital OR women clinic OR maternity hospital"),
        (["diabetes","thyroid","hormone","endocrine","insulin","blood sugar"], "endocrinology hospital OR diabetes clinic OR multispeciality hospital"),
        (["ear","hearing","ent","nose","throat","tonsil","sinusitis"], "ENT clinic OR ear nose throat clinic OR multispeciality hospital"),
        (["fever","cold","flu","infection","viral","bacterial","typhoid","malaria"], "general hospital OR medical clinic OR multispeciality hospital"),
        (["blood","anemia","hemoglobin","platelet"], "hematology clinic OR multispeciality hospital OR general hospital"),
    ]
    for keywords, specialty in rules:
        if any(w in q for w in keywords):
            return specialty
    return "multispeciality hospital OR general hospital OR medical clinic"

def search_hospitals(lat=None, lon=None, city=None, specialty="hospital"):
    hospitals, seen = [], set()
    headers = {"User-Agent":"HealixAI/1.0"}
    terms = [s.strip() for s in specialty.split("OR")] + ["multispeciality hospital","hospital","clinic"]
    for term in terms:
        if lat and lon:
            params = {"q":term,"format":"json","limit":5,"addressdetails":1,
                      "viewbox":f"{lon-0.1},{lat+0.1},{lon+0.1},{lat-0.1}","bounded":1}
        else:
            params = {"q":f"{term} in {city}","format":"json","limit":5,"addressdetails":1}
        try:
            r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers, timeout=10)
            for h in r.json():
                name = h.get("display_name","").split(",")[0]
                if name not in seen:
                    seen.add(name)
                    addr = ", ".join(h.get("display_name","").split(",")[1:4])
                    hospitals.append({"name":name,"address":addr,"lat":float(h["lat"]),"lon":float(h["lon"])})
        except: continue
        if len(hospitals) >= 8: break
    return hospitals[:8]

def save_booking(hospital, name, phone, age, date):
    f = "bookings.csv"
    exists = os.path.exists(f)
    with open(f,"a",newline="") as fp:
        w = csv.writer(fp)
        if not exists: w.writerow(["Hospital","Name","Phone","Age","Date","Booked At"])
        w.writerow([hospital,name,phone,age,date,datetime.now().strftime("%Y-%m-%d %H:%M")])

# ── Session state ──────────────────────────────────────────────────────────────
for k,v in {"messages":[],"show_hospitals":False,"hospitals":[],"booking_hospital":None,
            "detected_specialty":"multispeciality hospital OR general hospital",
            "user_lat":None,"user_lon":None,"user_location":"","city":"",
            "dark_mode":False,"page":"chat"}.items():
    if k not in st.session_state: st.session_state[k] = v

# ── GPS ────────────────────────────────────────────────────────────────────────
location = get_geolocation()
if location:
    try:
        lat, lon = location["coords"]["latitude"], location["coords"]["longitude"]
        if st.session_state.user_lat != lat:
            st.session_state.user_lat = lat
            st.session_state.user_lon = lon
            detected = get_city_from_coords(lat, lon)
            st.session_state.user_location = detected
            st.session_state.city = detected
    except: pass

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=DM+Serif+Display&display=swap');
*, *::before, *::after { box-sizing: border-box; }

.stApp { background:#F7F8FC; font-family:'Inter',system-ui,sans-serif; }
#MainMenu { display:none!important; }
footer { display:none!important; }
.stDeployButton { display:none!important; }
[data-testid="stToolbar"] { display:none!important; }
.block-container { padding:0!important; max-width:100%!important; }

/* ─────────────────────────────────────────────
   SIDEBAR OPEN STATE
   ───────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #0F172A !important;
    min-width: 260px !important;
    max-width: 260px !important;
}
[data-testid="stSidebar"] .stMarkdown { color: #94A3B8; }
[data-testid="stSidebarContent"] { padding: 0 !important; }

/* The ‹ collapse arrow INSIDE the open sidebar */
[data-testid="stSidebar"] [data-testid="stSidebarNavItems"],
[data-testid="stSidebar"] button {
    /* do NOT hide anything — let Streamlit render naturally */
}

/* ─────────────────────────────────────────────
   SIDEBAR COLLAPSED STATE  ← THE KEY FIX
   When sidebar is closed Streamlit renders a
   thin strip with the › arrow. We must give it
   a visible background + colored icon so the
   user can see and click it.
   ───────────────────────────────────────────── */
[data-testid="collapsedControl"] {
    background-color: #1E293B !important;
    border-right: 2px solid #3B82F6 !important;
    /* ensure it stays on top and is clickable */
    z-index: 999 !important;
    width: 2.5rem !important;
    min-height: 100vh !important;
    display: flex !important;
    align-items: flex-start !important;
    justify-content: center !important;
    padding-top: 1rem !important;
}

/* The › SVG arrow icon inside the collapsed strip */
[data-testid="collapsedControl"] svg {
    fill: #60A5FA !important;
    color: #60A5FA !important;
    width: 1.2rem !important;
    height: 1.2rem !important;
}

/* The actual button element wrapping the › icon */
[data-testid="collapsedControl"] button {
    background: transparent !important;
    border: none !important;
    color: #60A5FA !important;
    cursor: pointer !important;
    padding: 8px 6px !important;
    border-radius: 6px !important;
}
[data-testid="collapsedControl"] button:hover {
    background: rgba(96,165,250,0.15) !important;
}

/* Sidebar nav buttons */
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: none !important;
    color: #94A3B8 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    font-size: 13px !important;
    padding: 8px 14px !important;
    border-radius: 8px !important;
    width: 100% !important;
    margin: 1px 0 !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,.05) !important;
    color: #F1F5F9 !important;
}

/* Brand block */
.hx-brand { padding:24px 20px 16px; border-bottom:1px solid rgba(255,255,255,0.07); display:flex; align-items:center; gap:12px; }
.hx-logo { width:34px;height:34px;background:linear-gradient(135deg,#3B82F6,#06B6D4);border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:'DM Serif Display',serif;color:white;font-size:17px;flex-shrink:0; }
.hx-brand-name { font-size:14px;font-weight:600;color:#F1F5F9; }
.hx-brand-tag { font-size:10px;color:#64748B;letter-spacing:.05em;text-transform:uppercase; }
.hx-section-lbl { font-size:10px;font-weight:600;color:#475569;letter-spacing:.08em;text-transform:uppercase;padding:16px 20px 8px; }

/* Location pill */
.hx-loc { margin:8px 12px;background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);border-radius:8px;padding:10px 12px;display:flex;align-items:center;gap:8px; }
.hx-loc-dot { width:6px;height:6px;background:#10B981;border-radius:50%;animation:pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1}50%{opacity:.4} }
.hx-loc-text { font-size:12px;color:#6EE7B7; }
.hx-loc-sub  { font-size:10px;color:#34D399;opacity:.7; }

/* Recent chats */
.hx-hist { padding:6px 12px;border-radius:8px;font-size:12px;color:#64748B;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:1px 8px; }
.hx-hist:hover { background:rgba(255,255,255,.04);color:#94A3B8; }
.hx-hist-dot { color:#3B82F6;margin-right:6px;font-size:8px; }

/* Sidebar footer */
.hx-sb-footer { margin-top:auto;padding:14px 12px;border-top:1px solid rgba(255,255,255,.07); }

/* ── Topbar ── */
.hx-topbar { background:white;border-bottom:1px solid #E2E8F0;padding:14px 32px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:50; }
.hx-topbar-title { font-size:15px;font-weight:600;color:#0F172A; }
.hx-topbar-sub { font-size:12px;color:#94A3B8;margin-top:1px; }
.hx-status { display:flex;align-items:center;gap:6px;background:#F0FDF4;border:1px solid #BBF7D0;padding:5px 10px;border-radius:20px;font-size:12px;color:#16A34A;font-weight:500; }
.hx-status-dot { width:6px;height:6px;background:#22C55E;border-radius:50%; }

/* ── Content ── */
.hx-content { flex:1;padding:28px 32px;max-width:860px;width:100%;margin:0 auto; }
.hx-welcome-sub {
    text-align: center;
}

/* ── Welcome ── */
.hx-welcome { text-align:center;padding:50px 0 32px; }
.hx-welcome-icon { width:60px;height:60px;background:linear-gradient(135deg,#EFF6FF,#DBEAFE);border:1px solid #BFDBFE;border-radius:18px;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;font-size:26px; }
.hx-welcome-title { font-family:'DM Serif Display',serif;font-size:34px;color:#0F172A;letter-spacing:-.02em;margin:0 0 8px; }
.hx-welcome-sub { font-size:14px;color:#64748B;max-width:400px;margin:0 auto;line-height:1.6;text-align:center;width:100%; }
.hx-welcome-sub {text-align: center;}


/* ── Chip buttons ── */
div[data-testid="stHorizontalBlock"] .stButton > button {
    background: white !important;
    border: 1px solid #E2E8F0 !important;
    color: #475569 !important;
    border-radius: 20px !important;
    padding: 6px 14px !important;
    font-size: 12.5px !important;
    font-weight: 400 !important;
    transition: all .15s !important;
}
div[data-testid="stHorizontalBlock"] .stButton > button:hover {
    border-color: #3B82F6 !important;
    color: #3B82F6 !important;
    background: #EFF6FF !important;
}

/* ── Messages ── */
.hx-msgs { display:flex;flex-direction:column;gap:18px;margin-bottom:20px; }
.hx-msg { display:flex;gap:10px;align-items:flex-start; }
.hx-msg.user { flex-direction:row-reverse; }
.hx-av { width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex-shrink:0; }
.hx-av.bot { background:linear-gradient(135deg,#3B82F6,#06B6D4);color:white; }
.hx-av.user { background:#F1F5F9;color:#475569; }
.hx-bubble { max-width:78%;padding:12px 15px;border-radius:14px;font-size:13.5px;line-height:1.65; }
.hx-bubble.bot { background:white;border:1px solid #E2E8F0;border-radius:4px 14px 14px 14px;color:#1E293B; }
.hx-bubble.user { background:#0F172A;color:#F1F5F9;border-radius:14px 14px 4px 14px; }
.hx-meta { font-size:11px;color:#CBD5E1;margin-top:4px;padding:0 4px; }
.hx-msg.user .hx-meta { text-align:right; }
.hx-sources { display:flex;flex-wrap:wrap;gap:5px;margin-top:8px; }
.hx-src-pill { background:#EFF6FF;border:1px solid #BFDBFE;color:#2563EB;font-size:11px;padding:2px 8px;border-radius:20px;font-weight:500; }

/* ── Image Analysis ── */
.hx-analysis { background:white;border:1px solid #E2E8F0;border-radius:14px;padding:18px 20px;margin-top:14px; }
.hx-analysis-hdr { display:flex;align-items:center;gap:8px;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #F1F5F9; }
.hx-ai-badge { background:#FEF3C7;border:1px solid #FDE68A;color:#92400E;font-size:11px;font-weight:600;padding:2px 7px;border-radius:5px; }
.hx-analysis-body { font-size:13px;color:#334155;line-height:1.75;white-space:pre-wrap; }

/* ── Hospital section ── */
.hx-sec-hdr { display:flex;align-items:center;gap:10px;margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #F1F5F9; }
.hx-sec-icon { width:38px;height:38px;background:#EFF6FF;border:1px solid #BFDBFE;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:17px; }
.hx-sec-title { font-size:15px;font-weight:600;color:#0F172A;margin:0 0 1px; }
.hx-sec-sub { font-size:12px;color:#94A3B8; }
.hx-hosp-grid { display:flex;flex-direction:column;gap:8px;margin-top:14px; }
.hx-hosp-card { background:white;border:1px solid #E2E8F0;border-radius:12px;padding:14px 16px;display:flex;align-items:flex-start;justify-content:space-between;gap:10px;transition:border-color .15s,box-shadow .15s; }
.hx-hosp-card:hover { border-color:#93C5FD;box-shadow:0 2px 8px rgba(59,130,246,.08); }
.hx-hosp-ico { width:38px;height:38px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0; }
.hx-hosp-ico.hospital { background:#FEF2F2; } .hx-hosp-ico.clinic { background:#F0FDF4; } .hx-hosp-ico.multi { background:#EFF6FF; }
.hx-hosp-name { font-size:13.5px;font-weight:600;color:#0F172A;margin:0 0 2px; }
.hx-hosp-addr { font-size:12px;color:#94A3B8;margin:0 0 5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap; }
.hx-hosp-type { display:inline-flex;align-items:center;gap:3px;background:#F8FAFC;border:1px solid #E2E8F0;color:#64748B;font-size:11px;padding:2px 6px;border-radius:4px; }

/* ── Booking ── */
.hx-book-card { background:white;border:1px solid #E2E8F0;border-radius:14px;padding:22px;margin-top:20px; }
.hx-book-hosp { background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:10px 13px;font-size:13px;font-weight:500;color:#0F172A;margin-bottom:18px;display:flex;align-items:center;gap:7px; }
.hx-confirm { background:#F0FDF4;border:1px solid #BBF7D0;border-radius:12px;padding:18px 20px;margin-top:14px; }
.hx-confirm-title { font-size:14px;font-weight:600;color:#14532D;margin:0 0 10px; }
.hx-confirm-row { display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #D1FAE5;font-size:13px; }
.hx-confirm-row:last-child { border-bottom:none; }
.hx-confirm-lbl { color:#166534; } .hx-confirm-val { color:#14532D;font-weight:500; }

/* ── Form elements ── */
.stTextInput input,.stNumberInput input,.stTextArea textarea,.stDateInput input {
    border:1px solid #E2E8F0!important;border-radius:8px!important;
    font-family:'Inter',sans-serif!important;font-size:13.5px!important;
    padding:9px 13px!important;background:white!important;color:#0F172A!important;
}
.stTextInput input:focus,.stTextArea textarea:focus {
    border-color:#3B82F6!important;box-shadow:0 0 0 3px rgba(59,130,246,.1)!important;
}

/* Main action buttons */
.block-container .stButton > button {
    font-family:'Inter',sans-serif!important;font-size:13px!important;font-weight:500!important;
    border-radius:8px!important;padding:9px 16px!important;
    background:#0F172A!important;color:white!important;
    border:1px solid #0F172A!important;transition:all .15s!important;
}
.block-container .stButton > button:hover { background:#1E293B!important; }

.stChatInput,[data-testid="stChatInput"] { border:1px solid #E2E8F0!important;border-radius:12px!important;background:white!important; }
[data-testid="stChatInputTextArea"] { font-family:'Inter',sans-serif!important;font-size:13.5px!important; }
.stRadio label { font-size:13px!important;color:#334155!important; }
hr { border:none!important;border-top:1px solid #F1F5F9!important;margin:20px 0!important; }
[data-testid="stFileUploader"] { border:1.5px dashed #CBD5E1!important;border-radius:12px!important;background:white!important; }
[data-testid="stSidebar"] .stCheckbox label { color:#94A3B8!important;font-size:13px!important; }
</style>
""", unsafe_allow_html=True)

# Dark mode overlay
if st.session_state.dark_mode:
    st.markdown("""<style>
    .stApp { background:#0F172A!important; }
    .hx-topbar { background:#1E293B!important;border-color:#334155!important; }
    .hx-topbar-title { color:#F1F5F9!important; }
    .hx-topbar-sub { color:#64748B!important; }
    .hx-welcome-title { color:#F1F5F9!important; }
    .hx-welcome-sub { color:#94A3B8!important; }
    .hx-bubble.bot { background:#1E293B!important;border-color:#334155!important;color:#E2E8F0!important; }
    .hx-hosp-card { background:#1E293B!important;border-color:#334155!important; }
    .hx-hosp-name { color:#F1F5F9!important; }
    .hx-book-card { background:#1E293B!important;border-color:#334155!important; }
    .hx-book-hosp { background:#0F172A!important;border-color:#334155!important;color:#F1F5F9!important; }
    .hx-analysis { background:#1E293B!important;border-color:#334155!important; }
    .hx-analysis-body { color:#CBD5E1!important; }
    .stTextInput input,.stNumberInput input,.stTextArea textarea,.stDateInput input {
        background:#1E293B!important;color:#F1F5F9!important;border-color:#334155!important;
    }
    div[data-testid="stHorizontalBlock"] .stButton > button {
        background:#1E293B!important;border-color:#334155!important;color:#94A3B8!important;
    }
    /* Dark mode: keep collapsed control visible */
    [data-testid="collapsedControl"] {
        background-color: #0F172A !important;
        border-right: 2px solid #3B82F6 !important;
    }
    </style>""", unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="hx-brand">
        <div class="hx-logo">H</div>
        <div>
            <div class="hx-brand-name">Healix AI</div>
            <div class="hx-brand-tag">Medical Assistant</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="hx-section-lbl">Navigation</div>', unsafe_allow_html=True)
    nav_items = [
        ("💬 Chat", "chat"),
        ("🔬 Image Analysis", "image"),
        ("🏥 Find Hospitals", "hospitals"),
        ("📅 Appointments", "appointments"),
    ]
    for label, key in nav_items:
        if st.button(label, key=f"nav_{key}", use_container_width=True):
            st.session_state.page = key
            if key == "hospitals":
                st.session_state.show_hospitals = True
            st.rerun()

    st.markdown('<div class="hx-section-lbl">Location</div>', unsafe_allow_html=True)
    if st.session_state.user_location:
        st.markdown(f"""
        <div class="hx-loc">
            <div class="hx-loc-dot"></div>
            <div>
                <div class="hx-loc-text">{st.session_state.user_location}</div>
                <div class="hx-loc-sub">GPS · live</div>
            </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div style="padding:4px 20px 12px;font-size:12px;color:#64748B;">Detecting location…</div>', unsafe_allow_html=True)

    st.markdown('<div class="hx-section-lbl">Theme</div>', unsafe_allow_html=True)
    dark = st.checkbox("🌙 Dark mode", value=st.session_state.dark_mode, key="dark_toggle")
    if dark != st.session_state.dark_mode:
        st.session_state.dark_mode = dark
        st.rerun()

    st.markdown('<div class="hx-section-lbl">Recent chats</div>', unsafe_allow_html=True)
    user_msgs = [m for m in st.session_state.messages if m["role"]=="user"]
    if user_msgs:
        for m in user_msgs[-6:]:
            txt = m["content"][:36]+"…" if len(m["content"])>36 else m["content"]
            st.markdown(f'<div class="hx-hist"><span class="hx-hist-dot">●</span>{txt}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:12px;color:#475569;padding:4px 20px;">No conversations yet</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="hx-sb-footer">
        <div style="font-size:10px;color:#475569;text-align:center;">Powered by Llama 3 · ChromaDB · RAG</div>
    </div>""", unsafe_allow_html=True)

    if st.session_state.messages:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🗑 Clear conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

# ── Topbar ─────────────────────────────────────────────────────────────────────
loc_status = st.session_state.user_location or "Locating…"
st.markdown(f"""
<div class="hx-topbar">
    <div>
        <div class="hx-topbar-title">Medical AI Assistant</div>
        <div class="hx-topbar-sub">Ask anything about health, symptoms, or medications</div>
    </div>
    <div class="hx-status"><div class="hx-status-dot"></div>Online · {loc_status}</div>
</div>
<div class="hx-content">
""", unsafe_allow_html=True)

# ── Load chain ─────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Loading medical knowledge base…")
def load_chain():
    return build_rag_chain()
chain = load_chain()

# ── PAGE: Chat ─────────────────────────────────────────────────────────────────
if st.session_state.page == "chat":
    if not st.session_state.messages:
        st.markdown("""
        <div class="hx-welcome">
            <div class="hx-welcome-icon">🩺</div>
            <h1 class="hx-welcome-title">How can I help you today?</h1>
            <p style="text-justify: center;">Ask about symptoms, conditions, medications, or upload a medical image for AI analysis.</p>
        </div>""", unsafe_allow_html=True)

        chip_queries = [
            "What causes high blood pressure?",
            "Symptoms of diabetes",
            "Is my rash serious?",
            "Common cold vs flu",
            "When to see a doctor?",
        ]
        cols = st.columns(len(chip_queries))
        for i, q in enumerate(chip_queries):
            with cols[i]:
                if st.button(q, key=f"chip_{i}", use_container_width=True):
                    now = datetime.now().strftime("%I:%M %p")
                    st.session_state.messages.append({"role":"user","content":q,"time":now})
                    with st.spinner("Searching knowledge base…"):
                        answer, sources = ask(chain, q)
                    st.session_state.messages.append({"role":"assistant","content":answer,"time":now,"sources":sources})
                    st.session_state.detected_specialty = detect_specialty(q)
                    st.session_state.show_hospitals = True
                    st.session_state.hospitals = []
                    st.rerun()

    if st.session_state.messages:
        st.markdown('<div class="hx-msgs">', unsafe_allow_html=True)
        for m in st.session_state.messages:
            if m["role"] == "user":
                st.markdown(f"""
                <div class="hx-msg user">
                    <div class="hx-av user">You</div>
                    <div><div class="hx-bubble user">{m["content"]}</div><div class="hx-meta">{m.get("time","")}</div></div>
                </div>""", unsafe_allow_html=True)
            else:
                srcs = "".join(f'<span class="hx-src-pill">{s}</span>' for s in m.get("sources",[]))
                srcs_html = f'<div class="hx-sources">{srcs}</div>' if srcs else ""
                st.markdown(f"""
                <div class="hx-msg bot">
                    <div class="hx-av bot">H</div>
                    <div><div class="hx-bubble bot">{m["content"]}{srcs_html}</div><div class="hx-meta">{m.get("time","")}</div></div>
                </div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ── PAGE: Image Analysis ───────────────────────────────────────────────────────
elif st.session_state.page == "image":
    st.markdown("""
    <div style="padding:24px 0 16px;">
        <div style="font-size:22px;font-weight:700;color:#0F172A;margin-bottom:4px;">🔬 Medical Image Analysis</div>
        <div style="font-size:13px;color:#94A3B8;">Upload a photo and get instant AI-powered analysis</div>
    </div>""", unsafe_allow_html=True)

    uploaded = st.file_uploader("Upload a photo of your skin, wound, rash, or any medical image",
                                type=["jpg","jpeg","png","webp"], label_visibility="visible")
    if uploaded:
        c1, c2 = st.columns(2)
        with c1:
            st.image(uploaded, use_container_width=True)
        with c2:
            st.markdown('<div style="padding:10px 0;font-size:13px;font-weight:500;color:#0F172A;">Image ready ✅</div>', unsafe_allow_html=True)
            if st.button("Analyze image →", key="analyze_btn", use_container_width=True):
                with st.spinner("Analyzing…"):
                    img_bytes = uploaded.read()
                    mime = f"image/{uploaded.name.split('.')[-1].lower()}".replace("image/jpg","image/jpeg")
                    analysis = analyze_medical_image(img_bytes, mime)
                st.markdown(f"""
                <div class="hx-analysis">
                    <div class="hx-analysis-hdr">
                        <div class="hx-ai-badge">AI ANALYSIS</div>
                        <div style="font-size:14px;font-weight:600;color:#0F172A;">Medical Image Report</div>
                    </div>
                    <div class="hx-analysis-body">{analysis}</div>
                </div>""", unsafe_allow_html=True)
                now = datetime.now().strftime("%I:%M %p")
                st.session_state.messages += [
                    {"role":"user","content":"📸 Uploaded medical image for analysis","time":now},
                    {"role":"assistant","content":analysis,"time":now,"sources":[]}
                ]
                st.session_state.detected_specialty = detect_specialty(analysis)
                st.session_state.show_hospitals = True
                st.session_state.hospitals = []

# ── PAGE: Find Hospitals ───────────────────────────────────────────────────────
elif st.session_state.page == "hospitals":
    st.session_state.show_hospitals = True
    st.markdown("""
    <div style="padding:24px 0 16px;">
        <div style="font-size:22px;font-weight:700;color:#0F172A;margin-bottom:4px;">🏥 Find Hospitals</div>
        <div style="font-size:13px;color:#94A3B8;">Search nearby hospitals and clinics</div>
    </div>""", unsafe_allow_html=True)

# ── PAGE: Appointments ─────────────────────────────────────────────────────────
elif st.session_state.page == "appointments":
    st.markdown("""
    <div style="padding:24px 0 16px;">
        <div style="font-size:22px;font-weight:700;color:#0F172A;margin-bottom:4px;">📅 My Appointments</div>
        <div style="font-size:13px;color:#94A3B8;">Your booked appointments</div>
    </div>""", unsafe_allow_html=True)

    f = "bookings.csv"
    if os.path.exists(f):
        import pandas as pd
        df = pd.read_csv(f)
        if df.empty:
            st.info("No appointments booked yet.")
        else:
            st.dataframe(df, use_container_width=True)
    else:
        st.info("No appointments booked yet. Find a hospital and book an appointment!")
    st.stop()

# ── Hospital finder ─────────────────────────────────────────────────────────────
if st.session_state.show_hospitals:
    st.markdown("<hr>", unsafe_allow_html=True)
    specialty = st.session_state.detected_specialty
    first_spec = specialty.split("OR")[0].strip().title()

    st.markdown(f"""
    <div class="hx-sec-hdr">
        <div class="hx-sec-icon">🏥</div>
        <div>
            <div class="hx-sec-title">Nearby hospitals & clinics</div>
            <div class="hx-sec-sub">Based on your query · <span style="color:#2563EB;">{first_spec}</span></div>
        </div>
    </div>""", unsafe_allow_html=True)

    use_gps = st.session_state.user_lat is not None
    if use_gps:
        c1, c2 = st.columns(2)
        with c1: mode = st.radio("Search by", ["GPS location","Enter area manually"], horizontal=True, label_visibility="collapsed")
        with c2: st.success(f"📍 {st.session_state.user_location}")
    else:
        st.info("Allow location access, or enter your area below.")
        mode = "Enter area manually"

    city_input = ""
    if not use_gps or mode == "Enter area manually":
        city_input = st.text_input("Your area or city", placeholder="e.g. Bandra, Mumbai…", value=st.session_state.city)

    if st.button("Search hospitals →", use_container_width=True):
        with st.spinner("Finding nearby hospitals…"):
            if use_gps and mode == "GPS location":
                hospitals = search_hospitals(lat=st.session_state.user_lat, lon=st.session_state.user_lon, specialty=specialty)
            else:
                city = city_input or st.session_state.city
                st.session_state.city = city
                hospitals = search_hospitals(city=city, specialty=specialty)
            st.session_state.hospitals = hospitals

    if st.session_state.hospitals:
        st.markdown(f'<div style="font-size:13px;color:#64748B;margin:14px 0 4px;">Found <strong style="color:#0F172A;">{len(st.session_state.hospitals)}</strong> results near you</div>', unsafe_allow_html=True)

        first = st.session_state.hospitals[0]
        center = [st.session_state.user_lat, st.session_state.user_lon] if use_gps and mode=="GPS location" else [first["lat"],first["lon"]]
        m = folium.Map(location=center, zoom_start=14, tiles="CartoDB positron")
        if use_gps and mode=="GPS location":
            folium.Marker(center, popup="You", tooltip="📍 You", icon=folium.Icon(color="blue",icon="user")).add_to(m)
        for h in st.session_state.hospitals:
            folium.Marker([h["lat"],h["lon"]], popup=h["name"], tooltip=h["name"], icon=folium.Icon(color="red",icon="plus-sign")).add_to(m)
        st_folium(m, width=None, height=340)

        st.markdown('<div class="hx-hosp-grid">', unsafe_allow_html=True)
        for i, h in enumerate(st.session_state.hospitals):
            nl = h["name"].lower()
            if "clinic" in nl: ico, lbl, cls = "🏪","Clinic","clinic"
            elif any(x in nl for x in ["multispeciality","multi"]): ico, lbl, cls = "🏨","Multispeciality","multi"
            else: ico, lbl, cls = "🏥","Hospital","hospital"
            st.markdown(f"""
            <div class="hx-hosp-card">
                <div class="hx-hosp-ico {cls}">{ico}</div>
                <div style="flex:1;min-width:0;">
                    <div class="hx-hosp-name">{h["name"]}</div>
                    <div class="hx-hosp-addr">📍 {h["address"]}</div>
                    <div class="hx-hosp-type">🏷 {lbl}</div>
                </div>
            </div>""", unsafe_allow_html=True)
            if st.button("Book appointment", key=f"book_{i}"):
                st.session_state.booking_hospital = h["name"]
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    elif not st.session_state.hospitals and st.session_state.city:
        st.warning("No results found. Try your district or nearest large city.")

# ── Booking form ───────────────────────────────────────────────────────────────
if st.session_state.booking_hospital:
    st.markdown(f"""
    <div class="hx-book-card">
        <div style="font-size:15px;font-weight:600;color:#0F172A;margin-bottom:14px;">Book an appointment</div>
        <div class="hx-book-hosp">🏥 {st.session_state.booking_hospital}</div>
    </div>""", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Full name", placeholder="Your full name")
        age  = st.number_input("Age", min_value=1, max_value=120, value=30)
    with c2:
        phone = st.text_input("Phone number", placeholder="+91 00000 00000")
        date  = st.date_input("Preferred date", min_value=datetime.today())

    c3, c4 = st.columns(2)
    with c3:
        if st.button("Confirm booking →", use_container_width=True):
            if name and phone:
                save_booking(st.session_state.booking_hospital, name, phone, age, str(date))
                st.success("Appointment booked!")
                st.markdown(f"""
                <div class="hx-confirm">
                    <div class="hx-confirm-title">✓ Booking confirmed</div>
                    <div class="hx-confirm-row"><span class="hx-confirm-lbl">Hospital</span><span class="hx-confirm-val">{st.session_state.booking_hospital}</span></div>
                    <div class="hx-confirm-row"><span class="hx-confirm-lbl">Patient</span><span class="hx-confirm-val">{name}, {age} yrs</span></div>
                    <div class="hx-confirm-row"><span class="hx-confirm-lbl">Phone</span><span class="hx-confirm-val">{phone}</span></div>
                    <div class="hx-confirm-row"><span class="hx-confirm-lbl">Date</span><span class="hx-confirm-val">{date}</span></div>
                </div>""", unsafe_allow_html=True)
                st.balloons()
                st.session_state.booking_hospital = None
            else:
                st.error("Please fill in your name and phone number.")
    with c4:
        if st.button("Cancel", use_container_width=True):
            st.session_state.booking_hospital = None
            st.rerun()

st.markdown("</div>", unsafe_allow_html=True)

# ── Chat input ────────────────────────────────────────────────────────────────
if st.session_state.page == "chat":
    if prompt := st.chat_input("Ask Healix anything about your health…"):
        now = datetime.now().strftime("%I:%M %p")
        st.session_state.messages.append({"role":"user","content":prompt,"time":now})
        with st.spinner("Searching knowledge base…"):
            answer, sources = ask(chain, prompt)
        st.session_state.messages.append({"role":"assistant","content":answer,"time":now,"sources":sources})
        st.session_state.detected_specialty = detect_specialty(prompt)
        st.session_state.show_hospitals = True
        st.session_state.hospitals = []
        st.session_state.booking_hospital = None
        st.rerun()