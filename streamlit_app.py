# streamlit_app.py
import streamlit as st
from datetime import datetime, time
import pytz
from supabase import create_client, Client
import re
import time as tmode
import streamlit.components.v1 as components
import os

# -----------------------------
# Nastavenia DB (neukladaj do verejného kódu)
# -----------------------------
# DATABAZA_URL a DATABAZA_KEY daj do st.secrets (Streamlit cloud) alebo do env
if "DATABAZA_URL" in st.secrets:
    DATABAZA_URL = st.secrets["DATABAZA_URL"]
    DATABAZA_KEY = st.secrets["DATABAZA_KEY"]
else:
    DATABAZA_URL = os.environ.get("DATABAZA_URL")
    DATABAZA_KEY = os.environ.get("DATABAZA_KEY")

if not DATABAZA_URL or not DATABAZA_KEY:
    st.error("❌ Chýbajú prihlasovacie údaje do databázy. Skontroluj st.secrets alebo env vars.")
    st.stop()

databaza: Client = create_client(DATABAZA_URL, DATABAZA_KEY)

# -----------------------------
# Konštanty
# -----------------------------
tz = pytz.timezone("Europe/Bratislava")
POSITIONS = [
    "Veliteľ","CCTV","Brány","Sklad2",
    "Turniket2","Plombovac2","Sklad3",
    "Turniket3","Plombovac3"
]

# -----------------------------
# Pomocné funkcie
# -----------------------------
def valid_arrival(now):
    return (time(5,0) <= now.time() <= time(7,0)) or (time(13,0) <= now.time() <= time(15,0))

def valid_departure(now):
    return (time(13,30) <= now.time() <= time(15,0)) or (time(21,0) <= now.time() <= time(23,0))

def is_valid_code(code: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]{8}", code))

def verify_device_in_db(code: str) -> bool:
    """Skontroluje v DB, či je device code povolený (table 'devices' má stĺpec 'code')."""
    try:
        res = databaza.table("devices").select("code").eq("code", code.strip()).execute()
        return bool(res.data and len(res.data) > 0)
    except Exception as e:
        st.error("Chyba pri overovaní zariadenia v DB.")
        st.write(e)
        return False

def save_attendance(user_code, position, action, now=None):
    user_code = user_code.strip()
    if len(user_code) != 8:
        st.warning("⚠️ Neplatné číslo čipu!")
        return False
    if not now:
        now = datetime.now(tz)
    is_valid = valid_arrival(now) if action == "Príchod" else valid_departure(now)
    try:
        databaza.table("attendance").insert({
            "user_code": user_code,
            "position": position,
            "action": action,
            "timestamp": now.isoformat(),
            "valid": is_valid
        }).execute()
    except Exception as e:
        st.error("❌ Chyba pri ukladaní do DB. Skontroluj RLS/politiky.")
        st.write(e)
        return False
    return is_valid

# -----------------------------
# Helper: small JS component na čítanie localStorage a dočasné prenos do URL
# (pridá ?device_code=XXX a redirectne — Streamlit potom prečíta parametre)
# -----------------------------
def js_check_localstorage_and_redirect():
    js = """
    <script>
    (function(){
        try {
            const code = window.localStorage.getItem("device_code");
            if(code && code.length>0) {
                // pridáme do URL iba na moment, potom server (Streamlit) spracuje a my túto časť URL vyčistíme z appky
                const url = new URL(window.location.href);
                // ak tam už device_code nie je, pridajme ho a načítajme znovu
                if(!url.searchParams.get("device_code")) {
                    url.searchParams.set("device_code", code);
                    window.location.replace(url.toString());
                }
            }
        } catch(e) {
            // ignore
            console.log("localStorage check error", e);
        }
    })();
    </script>
    """
    components.html(js, height=0)

def js_save_device_code_and_clean_url(code: str):
    # uloží do localStorage a okamžite vyčistí query param z URL (history.replaceState)
    safe_code = code.replace('"', '\\"')
    js = f"""
    <script>
    (function(){
        try {{
            window.localStorage.setItem("device_code", "{safe_code}");
            // odstránime device_code z URL pre bezpečnosť
            const url = new URL(window.location.href);
            url.searchParams.delete("device_code");
            window.history.replaceState(null, '', url.pathname + url.search + url.hash);
        }} catch(e) {{
            console.log("save device code error", e);
        }}
    })();
    </script>
    """
    components.html(js, height=0)

def js_remove_device_code():
    js = """
    <script>
    (function(){
        try {
            window.localStorage.removeItem("device_code");
            // optional: reload page
            window.location.reload();
        } catch(e) { console.log(e); }
    })();
    </script>
    """
    components.html(js, height=0)

# -----------------------------
# Hlavná logika (device auth + zamestnanec view)
# -----------------------------
def zamestnanec_view():
    st.title("Dochádzka — Zamestnanec")

    # 1) Najprv spustíme JS, aby sme overili localStorage a prípadne redirectli s device_code v query param
    js_check_localstorage_and_redirect()

    # 2) Pozrieme query params (Streamlit prebral device_code počas redirectu)
    params = st.experimental_get_query_params()
    device_from_url = None
    if "device_code" in params and params["device_code"]:
        device_from_url = params["device_code"][0]

    # 3) Ak ešte nemáme device_code v session, použijeme device_from_url (to je z localStorage redirectu alebo z manuálneho zadania)
    if "device_code" not in st.session_state:
        st.session_state.device_code = None

    if device_from_url and not st.session_state.device_code:
        # overi v DB
        if verify_device_in_db(device_from_url):
            # uložíme do session a do localStorage (pomocou JS, ktorý zároveň odstráni param z URL)
            st.session_state.device_code = device_from_url
            js_save_device_code_and_clean_url(device_from_url)
            st.success("Zariadenie autorizované (uložené v prehliadači).")
            st.experimental_rerun()
        else:
            st.error("Kód zariadenia nie je povolený (z URL).")
            # odstráň param a pokračuj (môžeš tiež použiť js_remove to remove)
            # (nevoláme rerun, nech užívateľ zadá manuálne)

    # ak nie sme autorizovaní — ponúkame manuálne zadanie kódu
    if not st.session_state.device_code:
        st.subheader("Autorizácia zariadenia")
        input_code = st.text_input("Zadaj kód zariadenia (8 znakov; zadaj len raz na danom tablete)")
        if st.button("Potvrdiť kód"):
            if not input_code or not input_code.strip():
                st.warning("Zadaj platný kód.")
            elif not re.fullmatch(r"[A-Za-z0-9]{8}", input_code.strip()):
                st.warning("Kód musí mať 8 alfanumerických znakov.")
            else:
                if verify_device_in_db(input_code):
                    st.session_state.device_code = input_code.strip()
                    js_save_device_code_and_clean_url(input_code.strip())
                    st.success("Zariadenie autorizované ✅")
                    st.experimental_rerun()
                else:
                    st.error("Kód zariadenia nie je voľný / povolený v databáze.")
        st.info("Ak tento tablet už autorizoval admin, zadaj jeho kód. Iné zariadenia bez kódu sa neprihlásia.")
        return  # zatiaľ nechceme zobrazovať funkcie pre nezaregistrované zariadenie

    # -------------------------
    # Tu už sme autorizovaní → hlavné UI
    # -------------------------
    now = datetime.now(tz)
    st.subheader(f"🕒 Aktuálny čas: {now.strftime('%H:%M:%S')}")

    if st.button("🆕 Nový príchod/odchod"):
        st.session_state.temp_user_code = ""
        st.session_state.selected_position = None
        st.session_state.last_message = ""
        st.session_state.reload_counter = st.session_state.get("reload_counter", 0) + 1
        st.experimental_rerun()

    # QR / code input
    input_key = f"user_code_input_{st.session_state.get('reload_counter', 0)}"
    user_code = st.text_input("Naskenuj svoj QR kód", key=input_key, value=st.session_state.get("temp_user_code","")).replace(" ", "")

    # position selection
    st.write("👉 Vyber svoju pozíciu:")
    cols = st.columns(3)
    for i, pos in enumerate(POSITIONS):
        if cols[i % 3].button(pos):
            st.session_state.selected_position = pos

    if st.session_state.get("selected_position"):
        st.info(f"Vybraná pozícia: {st.session_state.selected_position}")

    def display_last_message(msg):
        if msg:
            placeholder = st.empty()
            placeholder.success(msg)
            tmode.sleep(2)
            placeholder.empty()

    col1, col2 = st.columns(2)
    if col1.button("✅ Príchod", key="prichod_btn"):
        if not user_code or not st.session_state.get("selected_position"):
            st.warning("Zadaj QR kód a vyber pozíciu.")
        elif not is_valid_code(user_code):
            st.error("Neplatné číslo čipu!")
        else:
            ok = save_attendance(user_code, st.session_state.selected_position, "Príchod", now)
            st.success(f"Príchod zaznamenaný {'(platný)' if ok else '(mimo času)'} ✅")
            # clear temp
            st.session_state.temp_user_code = ""
            st.session_state.selected_position = None
            st.session_state.reload_counter = st.session_state.get("reload_counter",0) + 1

    if col2.button("🚪 Odchod", key="odchod_btn"):
        if not user_code or not st.session_state.get("selected_position"):
            st.warning("Zadaj QR kód a vyber pozíciu.")
        elif not is_valid_code(user_code):
            st.error("Neplatné číslo čipu!")
        else:
            ok = save_attendance(user_code, st.session_state.selected_position, "Odchod", now)
            st.success(f"Odchod zaznamenaný {'(platný)' if ok else '(mimo času)'} ✅")
            st.session_state.temp_user_code = ""
            st.session_state.selected_position = None
            st.session_state.reload_counter = st.session_state.get("reload_counter",0) + 1

    # možnosť zrušiť autorizáciu zariadenia (vymaže localStorage)
    if st.button("❌ Zrušiť autorizáciu tohto zariadenia"):
        st.session_state.device_code = None
        js_remove_device_code()
        st.info("Autorizácia odstránená z tohto zariadenia (localStorage).")

# -----------------------------
# Spustenie app
# -----------------------------
def main():
    zamestnanec_view()

if __name__ == "__main__":
    main()
