import streamlit as st
import google.generativeai as genai
import requests
import json

# 1. SETUP PAGE
st.set_page_config(page_title="Cek Fakta AI (Pro)", page_icon="🛡️")
st.title("🛡️ Cek Fakta Berita Indonesia")
st.markdown("Tempelkan judul berita atau pesan WhatsApp yang mencurigakan di bawah ini.")

# 2. API SETUP
# We need TWO keys now: one for the Brain (Gemini), one for the Eyes (Serper)
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    serper_key = st.secrets["SERPER_API_KEY"] # We will add this to secrets soon
    genai.configure(api_key=gemini_key)
except FileNotFoundError:
    st.error("API Key tidak ditemukan. Harap set GEMINI_API_KEY dan SERPER_API_KEY di Streamlit Secrets.")
    st.stop()
except KeyError:
    st.error("Salah satu API Key hilang. Pastikan GEMINI_API_KEY dan SERPER_API_KEY ada di Secrets.")
    st.stop()

# Function to Search Google via Serper
def google_search(query):
    url = "https://google.serper.dev/search"
    payload = json.dumps({
        "q": query,
        "gl": "id", # Target Indonesia
        "hl": "id", # Language Indonesia
        "num": 5    # Number of results
    })
    headers = {
        'X-API-KEY': serper_key,
        'Content-Type': 'application/json'
    }
    try:
        response = requests.request("POST", url, headers=headers, data=payload)
        return response.json().get("organic", [])
    except:
        return []

# 3. USER INPUT
user_text = st.text_area("Masukkan teks di sini:", height=150, placeholder="Contoh: Prabowo bertemu PM Australia...")

if st.button("🔍 Cek Fakta Sekarang"):
    if not user_text:
        st.warning("Harap masukkan teks berita terlebih dahulu.")
    else:
        with st.spinner('Sedang melakukan investigasi mendalam...'):
            
            # 4. SEARCH (The "Eyes" - Upgraded to Google API)
            # We search for the text + 'berita' to ensure we get news
            search_query = f"{user_text} berita validasi"
            results = google_search(search_query)

            if not results:
                st.warning("Google tidak menemukan berita relevan. Coba kata kunci yang lebih spesifik.")
            else:
                # 5. PREPARE CONTEXT
                evidence_text = ""
                for doc in results:
                    evidence_text += f"- {doc.get('title', 'No Title')}: {doc.get('snippet', 'No snippet')} (Source: {doc.get('link')})\n"

                # 6. REASONING (The "Brain")
                prompt = f"""
                Peran: Kamu adalah "CekFaktaBot", investigator berita senior.
                
                TUGAS:
                Verifikasi KLAIM USER berdasarkan BUKTI PENCARIAN Google di bawah ini.
                
                KLAIM USER:
                "{user_text}"
                
                BUKTI PENCARIAN (Google Search):
                {evidence_text}
                
                ATURAN:
                1. Jika bukti berita mainstream (Kompas, CNN, Detik, Antara) mengonfirmasi peristiwa -> FAKTA.
                2. Jika tidak ada berita sama sekali tentang event ini -> TIDAK TERBUKTI.
                3. Jika sumber terpercaya membantah -> HOAKS.
                
                FORMAT OUTPUT (Markdown):
                ## ⚖️ Vonis: [FAKTA / HOAKS / SATIRE / TIDAK TERBUKTI]
                
                **Analisis:**
                [Jelaskan dalam 2 kalimat santai]
                
                **Sumber Valid:**
                * [Judul Berita](Link)
                """

                try:
                    model = genai.GenerativeModel('gemini-2.0-flash')
                    response = model.generate_content(prompt)
                    
                    # 7. OUTPUT
                    st.markdown("---")
                    st.markdown("### 🤖 Hasil Analisis AI:")
                    st.write(response.text)
                        
                except Exception as e:
                    st.error(f"Terjadi kesalahan pada AI: {e}")