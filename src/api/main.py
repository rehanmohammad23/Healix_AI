import os
import csv
import base64
import requests
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.retrieval.rag_chain import build_rag_chain, ask
from loguru import logger
from groq import Groq
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

app = FastAPI(title="Healix AI API")

# Enable CORS for developer ease
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Groq Client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# Global RAG chain reference
chain = None

@app.on_event("startup")
async def startup_event():
    import threading
    def load():
        global chain
        logger.info("Loading RAG chain in background...")
        chain = build_rag_chain()
        logger.info("RAG chain loaded successfully!")
    threading.Thread(target=load).start()

# --- Helpers ---

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
        logger.error(f"Image analysis failed: {e}")
        return f"Image analysis failed: {str(e)}"

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
        if lat is not None and lon is not None:
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
        except Exception as e:
            logger.warning(f"Error calling OSM Nominatim for term {term}: {e}")
            continue
        if len(hospitals) >= 8: break
    return hospitals[:8]

def save_booking(hospital, name, phone, age, date):
    f = "bookings.csv"
    exists = os.path.exists(f)
    with open(f,"a",newline="") as fp:
        w = csv.writer(fp)
        if not exists: w.writerow(["Hospital","Name","Phone","Age","Date","Booked At"])
        w.writerow([hospital,name,phone,age,date,datetime.now().strftime("%Y-%m-%d %H:%M")])

# --- Endpoints ---

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    if not chain:
        raise HTTPException(status_code=503, detail="RAG model is still loading, please wait.")
    try:
        answer, sources = ask(chain, request.message)
        specialty = detect_specialty(request.message)
        return {
            "answer": answer,
            "sources": sources,
            "specialty": specialty
        }
    except Exception as e:
        logger.exception("Error in chat endpoint")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze-image")
async def analyze_image_endpoint(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        mime_type = file.content_type or "image/jpeg"
        
        analysis = analyze_medical_image(image_bytes, mime_type)
        specialty = detect_specialty(analysis)
        
        return {
            "analysis": analysis,
            "specialty": specialty
        }
    except Exception as e:
        logger.exception("Error in image analysis endpoint")
        raise HTTPException(status_code=500, detail=str(e))

class GeocodeRequest(BaseModel):
    lat: float
    lon: float

@app.post("/api/reverse-geocode")
async def reverse_geocode_endpoint(req: GeocodeRequest):
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse",
            params={"lat":req.lat,"lon":req.lon,"format":"json","addressdetails":1},
            headers={"User-Agent":"HealixAI/1.0"}, timeout=10)
        print(r.json())   
        a = r.json().get("address", {})

        area = (
            a.get("suburb")
            or a.get("neighbourhood")
            or a.get("hamlet")
            or a.get("village")
            or a.get("quarter")
            or ""
        )

        city = (
            a.get("city")
            or a.get("town")
            or a.get("municipality")
            or a.get("county")
            or a.get("state_district")
            or a.get("state")
            or ""
        )

        if area and city and area != city:
            location_str = f"{area}, {city}"
        else:
            location_str = city or area

        return {"location": location_str}
    except Exception as e:
        logger.warning(f"Error reverse geocoding: {e}")
        return {"location": ""}

class HospitalSearchRequest(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    city: Optional[str] = None
    specialty: str

@app.post("/api/hospitals")
async def hospitals_endpoint(req: HospitalSearchRequest):
    try:
        hospitals = search_hospitals(lat=req.lat, lon=req.lon, city=req.city, specialty=req.specialty)
        return {"hospitals": hospitals}
    except Exception as e:
        logger.exception("Error in hospitals endpoint")
        raise HTTPException(status_code=500, detail=str(e))

class BookingRequest(BaseModel):
    hospital: str
    name: str
    phone: str
    age: int
    date: str

@app.post("/api/book")
async def book_endpoint(req: BookingRequest):
    try:
        save_booking(req.hospital, req.name, req.phone, req.age, req.date)
        return {"success": True}
    except Exception as e:
        logger.exception("Error in booking endpoint")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/appointments")
async def appointments_endpoint():
    f = "bookings.csv"
    if not os.path.exists(f):
        return {"appointments": []}
    try:
        appointments = []
        with open(f, mode="r", newline="", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                appointments.append(row)
        return {"appointments": appointments}
    except Exception as e:
        logger.exception("Error reading appointments file")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_endpoint():
    return {"status": "ok", "chain_loaded": chain is not None}

# Mount static files (will serve index.html at root)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")