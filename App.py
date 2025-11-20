import streamlit as st
import google.generativeai as genai
from duckduckgo_search import DDGS

# 1. SETUP
st.set_page_config(page_title="Cek Fakta AI", page_icon="🛡️")
st.title("🛡️ Cek Fakta Berita Indonesia")

# Get API Key from Streamlit Secrets (we will set this later)
api_key = st.secrets["GEMINI_API_KEY"] 
genai.configure(api_key=api_key)

# 2. INPUT
user_text = st.text_area("Masukkan judul atau isi berita yang mencurigakan:", height=100)

if st.button("Cek Fakta"):
    with st.spinner('Sedang mencari referensi di internet...'):
        
        # 3. SEARCH (The "Eyes")
        # Uses DuckDuckGo to search for the news text + "hoax" or "fakta"
        results = []
        with DDGS() as ddgs:
            # Search for the claim directly
            search_query = f"{user_text} fakta hoax indonesia"
            # Get top 5 results
            results = list(ddgs.text(search_query, region='id-id', max_results=5))

        if not results:
            st.error("Tidak ditemukan berita terkait. AI tidak dapat memverifikasi.")
        else:
            # 4. PREPARE CONTEXT
            evidence_text = ""
            for doc in results:
                evidence_text += f"- {doc['title']}: {doc['body']} (Link: {doc['href']})\n"

            # 5. REASONING (The "Brain")
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            prompt = f"""
            Kamu adalah Ahli Cek Fakta Indonesia. Tugasmu adalah memverifikasi klaim user berdasarkan bukti pencarian.
            
            KLAIM USER: "{user_text}"
            
            BUKTI PENCARIAN:
            {evidence_text}
            
            Instruksi:
            1. Bandingkan Klaim User dengan Bukti Pencarian.
            2. Tentukan status: "FAKTA", "HOAKS", "SATIRE", atau "TIDAK TERBUKTI".
            3. Berikan penjelasan singkat dalam Bahasa Indonesia yang santai tapi tegas.
            4. Sertakan sumber link yang relevan dari bukti.
            """

            response = model.generate_content(prompt)
            
            # 6. OUTPUT
            st.markdown("### Hasil Analisis AI:")
            st.write(response.text)
            
            st.markdown("### Sumber Referensi:")
            for doc in results:
                st.markdown(f"- [{doc['title']}]({doc['href']})")