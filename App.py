import streamlit as st
import google.generativeai as genai
import requests
import json
import pickle  # Essential for loading the brain
import re      # Essential for cleaning text
import os
from datetime import datetime
import locale

# Optional: Locale setup
try:
    locale.setlocale(locale.LC_TIME, 'id_ID.UTF-8')
except:
    pass
today_date = datetime.now().strftime("%A, %d %B %Y")

# 1. SETUP PAGE
st.set_page_config(page_title="Cek Fakta AI (Pro)", page_icon="🛡️", layout="wide")
st.title("🛡️ \"TPSC\" Cek Fakta Berita Indonesia")
st.markdown("Sistem ini menggunakan **Google Search** dengan **AI Detektor Hoaks** (Naive Bayes) untuk memfilter sumber berita.")


# 2. LOAD THE TRAINED MODEL

@st.cache_resource
def load_model():
    # Make sure 'hoax_detector_final.pkl' is in the same folder!
    model_path = "hoax_detector_final.pkl"
    
    if not os.path.exists(model_path):
        st.error(f"File model '{model_path}' tidak ditemukan. Harap upload file .pkl ke folder yang sama dengan app.py.")
        return None
        
    try:
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        return model
    except Exception as e:
        st.error(f"Gagal memuat model: {e}")
        return None

model = load_model()


# 3. TEXT CLEANING (Must match training logic exactly)

def clean_text_for_model(text):
    text = str(text)
    # Remove cheat tags
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)

    # Capture Style Tokens
    caps_count = sum(1 for c in text if c.isupper())
    length = len([c for c in text if c.isalpha()])
    style_tokens = ""
    
    if length > 0 and (caps_count / length) > 0.3: 
        style_tokens += " token_shouting "
    if "!!" in text or "??" in text:
        style_tokens += " token_excessive_bang "
    
    clickbait_triggers = ['viralkan', 'sebarkan', 'awas', 'hati-hati', 'terbongkar', 'mengejutkan']
    if any(word in text.lower() for word in clickbait_triggers):
        style_tokens += " token_clickbait "

    # Normalize
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text) 
    return text + style_tokens

# 4. API SETUP
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    serper_key = st.secrets["SERPER_API_KEY"]
    genai.configure(api_key=gemini_key)
except FileNotFoundError:
    st.error("Secrets file not found.")
    st.stop()

def google_search(query):
    url = "https://google.serper.dev/search"
    payload = json.dumps({
        "q": query,
        "gl": "id", "hl": "id", "num": 6 
    })
    headers = {'X-API-KEY': serper_key, 'Content-Type': 'application/json'}
    try:
        response = requests.post(url, headers=headers, data=payload)
        return response.json().get("organic", [])
    except:
        return []

# 5. USER INPUT
user_text = st.text_area("Masukkan teks di sini:", height=100, placeholder="Contoh: Prabowo bertemu PM Australia...")

if st.button("🔍 Cek Fakta Sekarang", type="primary"):
    if not user_text:
        st.warning("Harap masukkan teks berita terlebih dahulu.")
    else:
        with st.spinner('AI sedang menganalisis sumber informasi...'):
            
            # A. GOOGLE SEARCH
            search_query = f"{user_text} berita"
            results = google_search(search_query)

            if not results:
                st.warning("Google tidak menemukan berita relevan.")
            else:
                
                # B. FILTER RESULTS USING YOUR MODEL
                st.subheader("Analisis Kualitas Sumber (AI Filter)")
                
                scored_evidence = ""
                
                for doc in results:
                    title = doc.get('title', '')
                    snippet = doc.get('snippet', '')
                    full_text = f"{title} {snippet}"
                    link = doc.get('link')

                    # PREDICT
                    hoax_score = 0.5 # Default neutral
                    if model:
                        clean_input = clean_text_for_model(full_text)
                        try:
                            probs = model.predict_proba([clean_input])[0]
                            classes = model.classes_
                            hoax_idx = list(classes).index("Hoax")
                            hoax_score = probs[hoax_idx]
                        except:
                            pass

                    # DISPLAY RESULTS
                    # Filter sources based on the score
                    if hoax_score > 0.7:
                        st.markdown(f"⛔ **SUMBER MENCURIGAKAN (Skor Hoaks {hoax_score*100:.0f}%):** [{title}]({link})")
                        scored_evidence += f"- [SUMBER DIABAIKAN/CLICKBAIT] {title}: {snippet}\n"
                    elif hoax_score > 0.4:
                        st.markdown(f"⚠️ **NETRAL (Skor Hoaks {hoax_score*100:.0f}%):** [{title}]({link})")
                        scored_evidence += f"- [SUMBER NETRAL] {title}: {snippet}\n"
                    else:
                        st.markdown(f"✅ **TERPERCAYA (Skor Hoaks {hoax_score*100:.0f}%):** [{title}]({link})")
                        scored_evidence += f"- [SUMBER TERPERCAYA] {title}: {snippet}\n"

                # C. GEMINI GENERATION
                prompt = f"""
                Peran: Investigator Berita Senior.
                
                TUGAS:
                Verifikasi KLAIM USER berdasarkan BUKTI PENCARIAN yang sudah dinilai oleh AI Detektor Hoaks.

                KLAIM USER: "{user_text}"
                
                BUKTI BERITA (Dinilai oleh AI):
                {scored_evidence}
                
                ATURAN:
                1. Prioritaskan [SUMBER TERPERCAYA].
                2. Jika banyak sumber clickbait/diabaikan, beri peringatan.
                3. Jawab dengan tegas: FAKTA, HOAKS, atau TIDAK TERBUKTI.
                
                FORMAT OUTPUT:
                ## Vonis: [FAKTA / HOAKS / TIDAK TERBUKTI]
                **Analisis:** [Penjelasan]
                """

                try:
                    model_gemini = genai.GenerativeModel('gemini-2.0-flash')
                    response = model_gemini.generate_content(prompt)
                    
                    st.markdown("---")
                    st.markdown("###  Kesimpulan Akhir:")
                    st.write(response.text)
                        
                except Exception as e:
                    st.error(f"Terjadi kesalahan pada Gemini: {e}")