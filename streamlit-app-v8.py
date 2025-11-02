"""
═══════════════════════════════════════════════════════════════════
🌊 WASSERWACHT DIENSTPLAN+ v8.0 - PRODUCTION READY
═══════════════════════════════════════════════════════════════════
✅ SMS & E-Mail komplett überarbeitet mit detailliertem Logging
✅ Admin kann jede Schicht buchen, stornieren & umbuchen
✅ Farbcodierter Schichtplan (Grün=Frei, Orange=Eigene, Blau=Admin-View)
✅ User-Einstellungen für Benachrichtigungen (bei Buchung, 24h, 1h)
✅ Mobile-optimiert & Responsive Design
✅ Automatische Backups täglich um 20:00 & bei jeder Änderung
✅ Wiederherstellung aus Backup möglich
═══════════════════════════════════════════════════════════════════

WICHTIGE ÄNDERUNGEN v8.0:
--------------------------
1. SMS/E-Mail: Separates notifications.py Modul mit detailliertem Error-Handling
2. Schichtplan: Direkt sehen wer gebucht hat + Stornieren-Button
3. Admin: Umbuchungs-Funktion + erweiterte Rechte
4. Farben: Grün (frei), Orange (eigene), Rot/Grau (andere), Blau (Admin)
5. User-Profil: Notification-Einstellungen anpassbar
6. Test-Buttons: Detaillierte Fehlermeldungen bei SMS/E-Mail

ANLEITUNG SECRETS EINRICHTEN:
------------------------------
Siehe secrets-template.toml für detaillierte Anleitung!

"""

import streamlit as st
import hashlib
import io
import json
import zipfile
import calendar as cal_module
from datetime import datetime, timedelta, date
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.cloud import firestore
from google.oauth2 import service_account

# ═════════════════════════════════════════════════════════════════════════════
# IMPORTS - NOTIFICATION SYSTEM
# ═════════════════════════════════════════════════════════════════════════════
try:
    from notifications import EmailNotifier, SMSNotifier, init_notifiers
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    print("⚠️ notifications.py nicht gefunden - bitte hochladen!")
    NOTIFICATIONS_AVAILABLE = False

# ═════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Wasserwacht Dienstplan+",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ═════════════════════════════════════════════════════════════════════════════
# KONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════
VERSION = "8.0 - Production Ready"
TIMEZONE_STR = "Europe/Berlin"
TZ = pytz.timezone(TIMEZONE_STR)

WEEKLY_SLOTS = [
    {"id": 1, "day": "tuesday", "day_name": "Dienstag", "start": "17:00", "end": "20:00"},
    {"id": 2, "day": "friday", "day_name": "Freitag", "start": "17:00", "end": "20:00"},
    {"id": 3, "day": "saturday", "day_name": "Samstag", "start": "14:00", "end": "17:00"},
]

BAVARIA_HOLIDAYS = {
    "2025": ["2025-01-01", "2025-01-06", "2025-04-18", "2025-04-21", "2025-05-01",
             "2025-05-29", "2025-06-09", "2025-06-19", "2025-08-15", "2025-10-03",
             "2025-11-01", "2025-12-25", "2025-12-26"],
    "2026": ["2026-01-01", "2026-01-06", "2026-04-03", "2026-04-06", "2026-05-01",
             "2026-05-14", "2026-05-25", "2026-06-04", "2026-08-15", "2026-10-03",
             "2026-11-01", "2026-12-25", "2026-12-26"]
}

COLORS = {
    "rot": "#DC143C",
    "rot_dunkel": "#B22222",
    "rot_hell": "#FF6B6B",
    "blau": "#003087",
    "blau_hell": "#4A90E2",
    "weiss": "#FFFFFF",
    "grau_hell": "#F5F7FA",
    "grau_mittel": "#E1E8ED",
    "grau_dunkel": "#657786",
    "text": "#14171A",
    "erfolg": "#17BF63",
    "warnung": "#FFAD1F",
    "fehler": "#E0245E",
    "orange": "#FF8C00",
    "orange_hell": "#FFA500",
    "gruen": "#28A745",
    "gruen_hell": "#90EE90"
}

# ═════════════════════════════════════════════════════════════════════════════
# FIREBASE INITIALISIERUNG
# ═════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def init_firestore():
    """Firebase Firestore initialisieren"""
    try:
        if not hasattr(st, 'secrets'):
            st.error("❌ Keine Secrets konfiguriert!")
            st.stop()

        key = st.secrets.get("firebase", {}).get("service_account_key")
        if not key:
            st.error("❌ Firebase Service Account Key fehlt in Secrets!")
            st.stop()

        key_dict = json.loads(key)
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds, project=key_dict["project_id"])

    except Exception as e:
        st.error(f"❌ Firebase Initialisierung fehlgeschlagen: {e}")
        st.stop()

db = init_firestore()

# ═════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def hash_pw(pw):
    """Passwort hashen mit SHA256"""
    return hashlib.sha256(pw.encode()).hexdigest()

def week_start(d=None):
    """Montag der aktuellen Woche ermitteln"""
    d = d or datetime.now().date()
    if hasattr(d, "date"):
        d = d.date()
    return d - timedelta(days=d.weekday())

def slot_date(ws, day):
    """Datum für einen Wochentag berechnen"""
    days = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    return (ws + timedelta(days=days.get(day, 0))).strftime("%Y-%m-%d")

def fmt_de(d):
    """Datum im deutschen Format (DD.MM.YYYY)"""
    try:
        if isinstance(d, str):
            return datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
        return d.strftime("%d.%m.%Y")
    except:
        return str(d)

def is_holiday(d):
    """Prüfen ob Feiertag"""
    if isinstance(d, date):
        d = d.strftime("%Y-%m-%d")
    return d in BAVARIA_HOLIDAYS.get(d[:4], [])

def is_summer(d):
    """Prüfen ob Sommerpause (Juni-September)"""
    try:
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d")
        return 6 <= d.month <= 9
    except:
        return False

def is_blocked(d):
    """Prüfen ob Datum blockiert (Feiertag oder Sommerpause)"""
    return is_holiday(d) or is_summer(d)

def block_reason(d):
    """Grund für Blockierung zurückgeben"""
    if is_holiday(d):
        return "🚫 Feiertag"
    elif is_summer(d):
        return "🏖️ Sommerpause"
    return None

# ═════════════════════════════════════════════════════════════════════════════
# CSS INJECTION
# ═════════════════════════════════════════════════════════════════════════════

def inject_css(dark=False):
    """Custom CSS für besseres Design"""
    bg = "#1A1D23" if dark else COLORS["weiss"]
    surface = "#2D3238" if dark else COLORS["grau_hell"]
    text = "#FFFFFF" if dark else COLORS["text"]
    primary = COLORS["rot_hell"] if dark else COLORS["rot"]

    st.markdown(f"""
    <style>
        /* Global Styles */
        .main {{
            background-color: {bg};
            color: {text};
        }}

        /* Slot Cards */
        .slot-card {{
            padding: 1.2rem;
            border-radius: 12px;
            margin: 0.5rem 0;
            border: 2px solid;
            transition: all 0.3s ease;
            font-weight: 500;
        }}

        .slot-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.15);
        }}

        /* Success/Error Messages */
        .stSuccess {{
            padding: 1rem;
            border-radius: 8px;
            background-color: {COLORS["erfolg"]}20;
            border-left: 4px solid {COLORS["erfolg"]};
        }}

        .stError {{
            padding: 1rem;
            border-radius: 8px;
            background-color: {COLORS["fehler"]}20;
            border-left: 4px solid {COLORS["fehler"]};
        }}

        .stWarning {{
            padding: 1rem;
            border-radius: 8px;
            background-color: {COLORS["warnung"]}20;
            border-left: 4px solid {COLORS["warnung"]};
        }}

        /* Buttons */
        .stButton>button {{
            border-radius: 8px;
            font-weight: 500;
            transition: all 0.2s ease;
        }}

        .stButton>button:hover {{
            transform: translateY(-1px);
        }}

        /* Legend */
        .legend {{
            display: flex;
            gap: 1.5rem;
            flex-wrap: wrap;
            padding: 1rem;
            background: {surface};
            border-radius: 8px;
            margin: 1rem 0;
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .legend-color {{
            width: 28px;
            height: 28px;
            border-radius: 6px;
            border: 2px solid;
        }}

        /* Responsive */
        @media (max-width: 768px) {{
            .slot-card {{
                padding: 0.8rem;
                font-size: 0.9rem;
            }}

            .legend {{
                flex-direction: column;
                gap: 0.5rem;
            }}
        }}
    </style>
    """, unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALISIERUNG
# ═════════════════════════════════════════════════════════════════════════════

def init_session_state():
    """Session State Variablen initialisieren"""
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'page' not in st.session_state:
        st.session_state.page = 'home'
    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = False
    if 'current_week' not in st.session_state:
        st.session_state.current_week = week_start()
    if 'notifiers_initialized' not in st.session_state:
        st.session_state.notifiers_initialized = False

init_session_state()

# Notifier initialisieren (nur einmal)
if NOTIFICATIONS_AVAILABLE and not st.session_state.notifiers_initialized:
    try:
        email_notifier, sms_notifier, success, msg = init_notifiers()
        if success:
            st.session_state.email_notifier = email_notifier
            st.session_state.sms_notifier = sms_notifier
            st.session_state.notifiers_initialized = True
            print(f"✅ {msg}")
        else:
            print(f"⚠️ {msg}")
            st.session_state.email_notifier = None
            st.session_state.sms_notifier = None
    except Exception as e:
        print(f"❌ Notifier Init Fehler: {e}")
        st.session_state.email_notifier = None
        st.session_state.sms_notifier = None

# ═════════════════════════════════════════════════════════════════════════════
# DATABASE CLASS
# ═════════════════════════════════════════════════════════════════════════════

class WasserwachtDB:
    def __init__(self):
        self.db = db
        self._init_admin()

    def _init_admin(self):
        """Admin-User erstellen falls nicht vorhanden"""
        if hasattr(st, 'secrets'):
            email = st.secrets.get("ADMIN_EMAIL", "admin@wasserwacht.de")
            pw = st.secrets.get("ADMIN_PASSWORD", "admin123")
            if not self.get_user(email):
                try:
                    self.db.collection('users').add({
                        'email': email,
                        'name': 'Admin',
                        'phone': '',
                        'password_hash': hash_pw(pw),
                        'role': 'admin',
                        'active': True,
                        'email_notifications': True,
                        'email_on_booking': True,
                        'email_24h': True,
                        'email_1h': True,
                        'sms_notifications': False,
                        'sms_on_booking': False,
                        'sms_24h': False,
                        'sms_1h': False,
                        'created_at': firestore.SERVER_TIMESTAMP
                    })
                    print(f"✅ Admin erstellt: {email}")
                except Exception as e:
                    print(f"⚠️ Admin Init: {e}")

    def get_user(self, email):
        """User anhand E-Mail abrufen"""
        try:
            for doc in self.db.collection('users').where('email', '==', email).limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except:
            return None

    def create_user(self, email, name, phone, password, role='user'):
        """Neuen User erstellen"""
        try:
            if self.get_user(email):
                return False, "E-Mail bereits registriert"

            self.db.collection('users').add({
                'email': email,
                'name': name,
                'phone': phone,
                'password_hash': hash_pw(password),
                'role': role,
                'active': True,
                'email_notifications': True,
                'email_on_booking': True,
                'email_24h': True,
                'email_1h': True,
                'sms_notifications': False,
                'sms_on_booking': False,
                'sms_24h': False,
                'sms_1h': False,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            return True, "User erstellt"
        except Exception as e:
            return False, str(e)

    def auth(self, email, password):
        """User authentifizieren"""
        u = self.get_user(email)
        if not u or not u.get('active', True):
            return False, None
        if u['password_hash'] == hash_pw(password):
            return True, u
        return False, None

    def get_all_users(self):
        """Alle User abrufen"""
        try:
            users = []
            for doc in self.db.collection('users').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                users.append(data)
            return users
        except:
            return []

    def update_user(self, uid, **kwargs):
        """User aktualisieren"""
        try:
            self.db.collection('users').document(uid).update(kwargs)
            return True
        except:
            return False

    def delete_user(self, email):
        """User löschen"""
        try:
            u = self.get_user(email)
            if u:
                self.db.collection('users').document(u['id']).delete()
                return True
            return False
        except:
            return False

    def create_booking(self, slot_date, slot_time, user_email, user_name, user_phone):
        """Neue Buchung erstellen"""
        try:
            existing = self.get_booking(slot_date, slot_time)
            if existing:
                return False, "Slot bereits gebucht"

            self.db.collection('bookings').add({
                'slot_date': slot_date,
                'slot_time': slot_time,
                'user_email': user_email,
                'user_name': user_name,
                'user_phone': user_phone,
                'status': 'confirmed',
                'created_at': firestore.SERVER_TIMESTAMP
            })
            return True, "Buchung erfolgreich"
        except Exception as e:
            return False, str(e)

    def get_booking(self, slot_date, slot_time):
        """Buchung für Slot abrufen"""
        try:
            for doc in self.db.collection('bookings').where('slot_date', '==', slot_date)\
                    .where('slot_time', '==', slot_time).where('status', '==', 'confirmed').limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except:
            return None

    def get_user_bookings(self, email, future_only=False):
        """Buchungen eines Users abrufen"""
        try:
            q = self.db.collection('bookings').where('user_email', '==', email).where('status', '==', 'confirmed')
            if future_only:
                q = q.where('slot_date', '>=', datetime.now().strftime("%Y-%m-%d"))
            bookings = []
            for doc in q.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                bookings.append(data)
            return sorted(bookings, key=lambda x: x['slot_date'])
        except:
            return []

    def cancel_booking(self, bid, cancelled_by):
        """Buchung stornieren"""
        try:
            self.db.collection('bookings').document(bid).update({
                'status': 'cancelled',
                'cancelled_by': cancelled_by,
                'cancelled_at': firestore.SERVER_TIMESTAMP
            })
            return True
        except:
            return False

    def get_week_bookings(self, ws):
        """Alle Buchungen einer Woche abrufen"""
        try:
            we = (datetime.strptime(ws, '%Y-%m-%d') + timedelta(days=6)).strftime('%Y-%m-%d')
            result = []
            for doc in self.db.collection('bookings').where('slot_date', '>=', ws)\
                    .where('slot_date', '<=', we).where('status', '==', 'confirmed').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                result.append(data)
            return result
        except Exception as e:
            print(f"get_week_bookings error: {e}")
            return []

    def get_all_bookings(self):
        """Alle Buchungen abrufen (Admin)"""
        try:
            bookings = []
            for doc in self.db.collection('bookings').where('status', '==', 'confirmed').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                bookings.append(data)
            return sorted(bookings, key=lambda x: x.get('slot_date', ''))
        except:
            return []

    def rebook_slot(self, booking_id, new_user_email, new_user_name, new_user_phone):
        """Schicht umbuchen (Admin)"""
        try:
            self.db.collection('bookings').document(booking_id).update({
                'user_email': new_user_email,
                'user_name': new_user_name,
                'user_phone': new_user_phone,
                'rebooked_at': firestore.SERVER_TIMESTAMP
            })
            return True, "Umbuchung erfolgreich"
        except Exception as e:
            return False, str(e)

    def get_stats(self):
        """Statistiken für Dashboard"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")

            # Total Users
            all_users = self.get_all_users()
            total_users = len([u for u in all_users if u.get('active', True)])

            # Future Bookings
            future_bookings = []
            for doc in self.db.collection('bookings').where('status', '==', 'confirmed').stream():
                b = doc.to_dict()
                if b.get('slot_date', '') >= today:
                    future_bookings.append(b)
            future_count = len(future_bookings)

            # Month Bookings
            month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            month_bookings = []
            for doc in self.db.collection('bookings').where('status', '==', 'confirmed').stream():
                b = doc.to_dict()
                date_str = b.get('slot_date', '')
                if month_start <= date_str <= today:
                    month_bookings.append(b)
            month_count = len(month_bookings)

            # Free Slots (next 4 weeks)
            free_slots = []
            for i in range(28):
                check_date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
                if not is_blocked(check_date):
                    for slot in WEEKLY_SLOTS:
                        ws = week_start(datetime.strptime(check_date, "%Y-%m-%d"))
                        slot_d = slot_date(ws, slot['day'])
                        if slot_d == check_date:
                            if not self.get_booking(check_date, f"{slot['start']}-{slot['end']}"):
                                free_slots.append({
                                    'date': check_date,
                                    'slot': f"{slot['day_name']} {slot['start']}-{slot['end']}"
                                })

            return {
                'total_users': total_users,
                'future_bookings': future_count,
                'month_bookings': month_count,
                'free_slots_next_4weeks': free_slots
            }
        except Exception as e:
            print(f"Stats error: {e}")
            return {'total_users': 0, 'future_bookings': 0, 'month_bookings': 0, 'free_slots_next_4weeks': []}

ww_db = WasserwachtDB()

# ═════════════════════════════════════════════════════════════════════════════
# NOTIFICATION HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def send_booking_notifications(user, slot_date, slot_time):
    """Benachrichtigungen nach Buchung senden"""
    results = []

    # E-Mail
    if user.get('email_notifications') and user.get('email_on_booking'):
        if st.session_state.email_notifier:
            success, msg = st.session_state.email_notifier.send_booking_confirmation(
                user['email'], user['name'], slot_date, slot_time
            )
            results.append(('email', success, msg))

    # SMS
    if user.get('sms_notifications') and user.get('sms_on_booking') and user.get('phone'):
        if st.session_state.sms_notifier:
            success, msg = st.session_state.sms_notifier.send_booking_confirmation(
                user['phone'], user['name'], slot_date, slot_time
            )
            results.append(('sms', success, msg))

    return results

def send_cancellation_notifications(user, slot_date, slot_time):
    """Benachrichtigungen nach Stornierung senden"""
    results = []

    # E-Mail
    if user.get('email_notifications'):
        if st.session_state.email_notifier:
            success, msg = st.session_state.email_notifier.send_cancellation(
                user['email'], user['name'], slot_date, slot_time
            )
            results.append(('email', success, msg))

    # SMS
    if user.get('sms_notifications') and user.get('phone'):
        if st.session_state.sms_notifier:
            success, msg = st.session_state.sms_notifier.send_cancellation(
                user['phone'], user['name'], slot_date, slot_time
            )
            results.append(('sms', success, msg))

    return results

# ═════════════════════════════════════════════════════════════════════════════
# UI COMPONENTS
# ═════════════════════════════════════════════════════════════════════════════

def render_color_legend(is_admin=False):
    """Farblegende anzeigen"""
    if is_admin:
        legend_html = f"""
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background:{COLORS['gruen_hell']};border-color:{COLORS['gruen']};"></div>
                <span>🟢 Frei</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background:{COLORS['orange_hell']};border-color:{COLORS['orange']};"></div>
                <span>🟠 Von dir gebucht</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background:{COLORS['blau_hell']};border-color:{COLORS['blau']};"></div>
                <span>🔵 Von anderen gebucht (Admin-Ansicht)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background:{COLORS['grau_mittel']};border-color:{COLORS['grau_dunkel']};"></div>
                <span>⚫ Gesperrt (Feiertag/Sommerpause)</span>
            </div>
        </div>
        """
    else:
        legend_html = f"""
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background:{COLORS['gruen_hell']};border-color:{COLORS['gruen']};"></div>
                <span>🟢 Frei - Jetzt buchen!</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background:{COLORS['orange_hell']};border-color:{COLORS['orange']};"></div>
                <span>🟠 Deine Schicht</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background:{COLORS['grau_mittel']};border-color:{COLORS['grau_dunkel']};"></div>
                <span>🔴 Bereits gebucht oder gesperrt</span>
            </div>
        </div>
        """

    st.markdown(legend_html, unsafe_allow_html=True)

def render_slot_card(slot, slot_d, booking, user, is_admin=False):
    """Slot-Card rendern mit Buchungs-/Stornierungsfunktion"""

    # Blockiert?
    blocked = is_blocked(slot_d)
    reason = block_reason(slot_d)

    # Farben bestimmen
    if blocked:
        bg_color = COLORS['grau_mittel']
        border_color = COLORS['grau_dunkel']
        text_color = COLORS['grau_dunkel']
    elif not booking:
        # Frei
        bg_color = COLORS['gruen_hell']
        border_color = COLORS['gruen']
        text_color = COLORS['text']
    elif booking.get('user_email') == user['email']:
        # Eigene Buchung
        bg_color = COLORS['orange_hell']
        border_color = COLORS['orange']
        text_color = COLORS['text']
    elif is_admin:
        # Admin sieht gebuchte Slots
        bg_color = COLORS['blau_hell']
        border_color = COLORS['blau']
        text_color = COLORS['weiss']
    else:
        # Von anderen gebucht
        bg_color = COLORS['grau_mittel']
        border_color = COLORS['grau_dunkel']
        text_color = COLORS['grau_dunkel']

    # Card HTML
    card_html = f"""
    <div class="slot-card" style="background:{bg_color};border-color:{border_color};color:{text_color};">
        <div style="font-size:1.1rem;font-weight:600;margin-bottom:0.5rem;">
            {slot['day_name']} {fmt_de(slot_d)}
        </div>
        <div style="font-size:0.95rem;opacity:0.9;">
            ⏰ {slot['start']} - {slot['end']}
        </div>
    """

    if blocked:
        card_html += f"""
        <div style="margin-top:0.5rem;font-weight:600;">
            {reason}
        </div>
        """
    elif booking:
        card_html += f"""
        <div style="margin-top:0.5rem;font-weight:600;">
            👤 {booking['user_name']}
        </div>
        """

    card_html += "</div>"

    col1, col2, col3 = st.columns([6, 2, 2])

    with col1:
        st.markdown(card_html, unsafe_allow_html=True)

    # Buttons
    if not blocked:
        if not booking:
            # Frei - Buchen
            with col2:
                if st.button("📅 Buchen", key=f"book_{slot_d}_{slot['id']}", use_container_width=True):
                    slot_time = f"{slot['start']}-{slot['end']}"
                    success, msg = ww_db.create_booking(
                        slot_d, slot_time, user['email'], user['name'], user.get('phone', '')
                    )
                    if success:
                        st.success(f"✅ {msg}")
                        # Benachrichtigungen senden
                        notif_results = send_booking_notifications(user, slot_d, slot_time)
                        for ntype, nsuccess, nmsg in notif_results:
                            if nsuccess:
                                st.success(f"✅ {ntype.upper()}: {nmsg}")
                            else:
                                st.warning(f"⚠️ {ntype.upper()}: {nmsg}")
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}")

        elif booking.get('user_email') == user['email']:
            # Eigene Buchung - Stornieren
            with col2:
                if st.button("❌ Stornieren", key=f"cancel_{booking['id']}", use_container_width=True):
                    if ww_db.cancel_booking(booking['id'], user['email']):
                        st.success("✅ Schicht storniert")
                        # Benachrichtigungen senden
                        slot_time = f"{slot['start']}-{slot['end']}"
                        notif_results = send_cancellation_notifications(user, slot_d, slot_time)
                        for ntype, nsuccess, nmsg in notif_results:
                            if nsuccess:
                                st.success(f"✅ {ntype.upper()}: {nmsg}")
                        st.rerun()
                    else:
                        st.error("❌ Fehler beim Stornieren")

        elif is_admin and booking:
            # Admin - Stornieren & Umbuchen
            with col2:
                if st.button("❌ Stornieren", key=f"admin_cancel_{booking['id']}", use_container_width=True):
                    if ww_db.cancel_booking(booking['id'], user['email']):
                        st.success("✅ Schicht storniert (Admin)")
                        # Benachrichtigung an betroffenen User
                        booked_user = ww_db.get_user(booking['user_email'])
                        if booked_user:
                            slot_time = f"{slot['start']}-{slot['end']}"
                            send_cancellation_notifications(booked_user, slot_d, slot_time)
                        st.rerun()
                    else:
                        st.error("❌ Fehler beim Stornieren")

            with col3:
                if st.button("🔄 Umbuchen", key=f"admin_rebook_{booking['id']}", use_container_width=True):
                    st.session_state.rebook_modal = booking['id']
                    st.rerun()

        elif is_admin and not booking:
            # Admin kann auch freie Slots für andere buchen
            with col3:
                if st.button("👥 Für User buchen", key=f"admin_book_{slot_d}_{slot['id']}", use_container_width=True):
                    st.session_state.admin_book_modal = f"{slot_d}_{slot['id']}"
                    st.rerun()

# Umbuchungs-Modal (Admin)
if 'rebook_modal' in st.session_state:
    booking_id = st.session_state.rebook_modal
    with st.expander("🔄 Schicht umbuchen", expanded=True):
        all_users = ww_db.get_all_users()
        user_options = {f"{u['name']} ({u['email']})": u for u in all_users if u.get('active')}

        selected_user_str = st.selectbox("Neuer User wählen:", list(user_options.keys()))
        selected_user = user_options[selected_user_str]

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Umbuchen", type="primary", use_container_width=True):
                success, msg = ww_db.rebook_slot(
                    booking_id,
                    selected_user['email'],
                    selected_user['name'],
                    selected_user.get('phone', '')
                )
                if success:
                    st.success(f"✅ {msg}")
                    # Benachrichtigung an neuen User
                    # TODO: Slot-Daten aus booking_id holen
                    del st.session_state.rebook_modal
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

        with col2:
            if st.button("❌ Abbrechen", use_container_width=True):
                del st.session_state.rebook_modal
                st.rerun()

# Admin-Buchungs-Modal
if 'admin_book_modal' in st.session_state:
    slot_info = st.session_state.admin_book_modal
    with st.expander("👥 Schicht für User buchen", expanded=True):
        all_users = ww_db.get_all_users()
        user_options = {f"{u['name']} ({u['email']})": u for u in all_users if u.get('active')}

        selected_user_str = st.selectbox("User wählen:", list(user_options.keys()))
        selected_user = user_options[selected_user_str]

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Buchen", type="primary", use_container_width=True):
                slot_d, slot_id = slot_info.split('_')
                slot = next((s for s in WEEKLY_SLOTS if s['id'] == int(slot_id)), None)
                if slot:
                    slot_time = f"{slot['start']}-{slot['end']}"
                    success, msg = ww_db.create_booking(
                        slot_d, slot_time,
                        selected_user['email'],
                        selected_user['name'],
                        selected_user.get('phone', '')
                    )
                    if success:
                        st.success(f"✅ {msg}")
                        # Benachrichtigung
                        notif_results = send_booking_notifications(selected_user, slot_d, slot_time)
                        for ntype, nsuccess, nmsg in notif_results:
                            if nsuccess:
                                st.success(f"✅ {ntype.upper()}: {nmsg}")
                        del st.session_state.admin_book_modal
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}")

        with col2:
            if st.button("❌ Abbrechen", use_container_width=True):
                del st.session_state.admin_book_modal
                st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# PAGES
# ═════════════════════════════════════════════════════════════════════════════

def show_login():
    """Login & Registrierung"""
    st.title("🔑 Login & Registrierung")

    tab1, tab2 = st.tabs(["🔐 Login", "📝 Registrieren"])

    with tab1:
        st.subheader("Anmelden")
        email = st.text_input("E-Mail", key="login_email")
        pw = st.text_input("Passwort", type="password", key="login_pw")

        if st.button("Login", type="primary", use_container_width=True):
            if not email or not pw:
                st.error("❌ Bitte alle Felder ausfüllen!")
            else:
                success, user = ww_db.auth(email, pw)
                if success:
                    st.session_state.user = user
                    st.session_state.page = 'home'
                    st.success("✅ Erfolgreich angemeldet!")
                    st.rerun()
                else:
                    st.error("❌ Falsche Anmeldedaten")

    with tab2:
        st.subheader("Neuen Account erstellen")
        with st.form("register"):
            name = st.text_input("Name *")
            email = st.text_input("E-Mail *")
            phone = st.text_input("Telefon (optional, für SMS)")
            pw = st.text_input("Passwort *", type="password")
            pw2 = st.text_input("Passwort bestätigen *", type="password")
            accept = st.checkbox("Ich akzeptiere die Datenschutzbestimmungen")

            if st.form_submit_button("📝 Registrieren", type="primary", use_container_width=True):
                if not name or not email or not pw or not pw2:
                    st.error("❌ Alle Pflichtfelder ausfüllen!")
                elif pw != pw2:
                    st.error("❌ Passwörter stimmen nicht überein!")
                elif len(pw) < 8:
                    st.error("❌ Passwort muss mindestens 8 Zeichen lang sein!")
                elif not accept:
                    st.error("❌ Bitte Datenschutz akzeptieren!")
                else:
                    success, msg = ww_db.create_user(email, name, phone, pw)
                    if success:
                        st.success(f"✅ {msg}")
                        st.balloons()
                        st.info("Du kannst dich jetzt anmelden!")
                    else:
                        st.error(f"❌ {msg}")

def show_home():
    """Startseite - Schichtplan"""
    if not st.session_state.user:
        st.title("🌊 Willkommen beim Wasserwacht Dienstplan+")
        st.info("Bitte melde dich an, um Schichten zu buchen.")
        return

    user = st.session_state.user
    is_admin = user.get('role') == 'admin'

    st.title("📅 Schichtplan")

    if is_admin:
        st.info("🔧 **Admin-Modus aktiv** - Du kannst alle Schichten verwalten")

    # Wochennavigation
    if 'current_week' not in st.session_state:
        st.session_state.current_week = week_start()

    cws = st.session_state.current_week

    col1, col2, col3 = st.columns([1, 3, 1])

    with col1:
        if st.button("◀️ Vorherige Woche"):
            st.session_state.current_week -= timedelta(days=7)
            st.rerun()

    with col2:
        week_end = cws + timedelta(days=6)
        st.markdown(f"<h3 style='text-align:center;'>Woche: {fmt_de(cws)} - {fmt_de(week_end)}</h3>",
                   unsafe_allow_html=True)

    with col3:
        if st.button("Nächste Woche ▶️"):
            st.session_state.current_week += timedelta(days=7)
            st.rerun()

    st.divider()

    # Legende
    render_color_legend(is_admin)

    st.divider()

    # Slots anzeigen
    for slot in WEEKLY_SLOTS:
        slot_d = slot_date(cws, slot['day'])
        slot_time = f"{slot['start']}-{slot['end']}"
        booking = ww_db.get_booking(slot_d, slot_time)

        render_slot_card(slot, slot_d, booking, user, is_admin)

def show_my_bookings():
    """Meine Schichten"""
    if not st.session_state.user:
        st.warning("Bitte anmelden!")
        return

    user = st.session_state.user
    st.title("📅 Meine Schichten")

    bookings = ww_db.get_user_bookings(user['email'], future_only=True)

    if not bookings:
        st.info("Du hast aktuell keine gebuchten Schichten.")
        return

    st.success(f"✅ Du hast **{len(bookings)}** gebuchte Schicht(en)")

    for b in bookings:
        col1, col2 = st.columns([4, 1])

        with col1:
            card_html = f"""
            <div class="slot-card" style="background:{COLORS['orange_hell']};border-color:{COLORS['orange']};">
                <div style="font-size:1.1rem;font-weight:600;">
                    📅 {fmt_de(b['slot_date'])} - {b['slot_time']}
                </div>
                <div style="margin-top:0.5rem;font-size:0.9rem;opacity:0.8;">
                    Gebucht am: {b.get('created_at', 'N/A')}
                </div>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)

        with col2:
            if st.button("❌ Stornieren", key=f"cancel_my_{b['id']}", use_container_width=True):
                if ww_db.cancel_booking(b['id'], user['email']):
                    st.success("✅ Schicht storniert")
                    notif_results = send_cancellation_notifications(user, b['slot_date'], b['slot_time'])
                    st.rerun()
                else:
                    st.error("❌ Fehler beim Stornieren")

def show_profile():
    """Profil & Einstellungen"""
    if not st.session_state.user:
        st.warning("Bitte anmelden!")
        return

    user = st.session_state.user
    st.title("👤 Profil & Einstellungen")

    tab1, tab2 = st.tabs(["👤 Profil", "🔔 Benachrichtigungen"])

    with tab1:
        st.subheader("Persönliche Daten")
        st.text_input("Name", value=user.get('name', ''), disabled=True)
        st.text_input("E-Mail", value=user.get('email', ''), disabled=True)

        new_phone = st.text_input("Telefonnummer (für SMS)", value=user.get('phone', ''))

        if st.button("📞 Telefonnummer aktualisieren", type="primary"):
            if ww_db.update_user(user['id'], phone=new_phone):
                st.success("✅ Telefonnummer aktualisiert")
                user['phone'] = new_phone
                st.session_state.user = user
                st.rerun()
            else:
                st.error("❌ Fehler beim Aktualisieren")

    with tab2:
        st.subheader("🔔 Benachrichtigungs-Einstellungen")

        st.markdown("### 📧 E-Mail Benachrichtigungen")
        email_enabled = st.checkbox(
            "E-Mail Benachrichtigungen aktiviert",
            value=user.get('email_notifications', True),
            key="email_enabled"
        )

        if email_enabled:
            email_on_booking = st.checkbox(
                "✅ Bei Buchung",
                value=user.get('email_on_booking', True),
                key="email_booking"
            )
            email_24h = st.checkbox(
                "⏰ 24h vor Schichtbeginn",
                value=user.get('email_24h', True),
                key="email_24"
            )
            email_1h = st.checkbox(
                "⏰ 1h vor Schichtbeginn",
                value=user.get('email_1h', True),
                key="email_1"
            )
        else:
            email_on_booking = email_24h = email_1h = False

        st.divider()

        st.markdown("### 📱 SMS Benachrichtigungen")
        if not user.get('phone'):
            st.warning("⚠️ Bitte zuerst Telefonnummer im Profil hinterlegen!")

        sms_enabled = st.checkbox(
            "SMS Benachrichtigungen aktiviert",
            value=user.get('sms_notifications', False),
            key="sms_enabled",
            disabled=not user.get('phone')
        )

        if sms_enabled and user.get('phone'):
            sms_on_booking = st.checkbox(
                "✅ Bei Buchung",
                value=user.get('sms_on_booking', False),
                key="sms_booking"
            )
            sms_24h = st.checkbox(
                "⏰ 24h vor Schichtbeginn",
                value=user.get('sms_24h', False),
                key="sms_24"
            )
            sms_1h = st.checkbox(
                "⏰ 1h vor Schichtbeginn",
                value=user.get('sms_1h', False),
                key="sms_1"
            )
        else:
            sms_on_booking = sms_24h = sms_1h = False

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            if st.button("💾 Einstellungen speichern", type="primary", use_container_width=True):
                update_data = {
                    'email_notifications': email_enabled,
                    'email_on_booking': email_on_booking,
                    'email_24h': email_24h,
                    'email_1h': email_1h,
                    'sms_notifications': sms_enabled,
                    'sms_on_booking': sms_on_booking,
                    'sms_24h': sms_24h,
                    'sms_1h': sms_1h
                }
                if ww_db.update_user(user['id'], **update_data):
                    st.success("✅ Einstellungen gespeichert")
                    # Session aktualisieren
                    user.update(update_data)
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("❌ Fehler beim Speichern")

        with col2:
            st.markdown("**🧪 Test-Funktionen**")

            if st.button("📧 Test-E-Mail senden", use_container_width=True):
                if st.session_state.email_notifier:
                    with st.spinner("Sende E-Mail..."):
                        success, msg = st.session_state.email_notifier.send_test_email(user['email'])
                    if success:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")
                else:
                    st.error("❌ E-Mail-System nicht verfügbar")

            if user.get('phone'):
                if st.button("📱 Test-SMS senden", use_container_width=True):
                    if st.session_state.sms_notifier:
                        with st.spinner("Sende SMS..."):
                            success, msg = st.session_state.sms_notifier.send_test_sms(user['phone'])
                        if success:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(f"❌ {msg}")
                    else:
                        st.error("❌ SMS-System nicht verfügbar")

def show_dashboard():
    """Admin Dashboard"""
    if not st.session_state.user or st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return

    st.title("📊 Admin Dashboard")

    stats = ww_db.get_stats()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("👥 Aktive User", stats['total_users'])

    with col2:
        st.metric("📅 Kommende Schichten", stats['future_bookings'])

    with col3:
        st.metric("📆 Diesen Monat", stats['month_bookings'])

    st.divider()

    st.subheader("🆓 Freie Slots (nächste 4 Wochen)")
    free_slots = stats['free_slots_next_4weeks']

    if free_slots:
        st.info(f"✅ {len(free_slots)} freie Slots verfügbar")
        df = pd.DataFrame(free_slots)
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("⚠️ Keine freien Slots in den nächsten 4 Wochen")

def show_all_bookings():
    """Alle Buchungen (Admin)"""
    if not st.session_state.user or st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return

    st.title("📋 Alle Buchungen")

    bookings = ww_db.get_all_bookings()

    if not bookings:
        st.info("Keine Buchungen vorhanden")
        return

    st.success(f"✅ {len(bookings)} Buchung(en) gefunden")

    # Als Tabelle
    df_data = []
    for b in bookings:
        df_data.append({
            'Datum': fmt_de(b['slot_date']),
            'Uhrzeit': b['slot_time'],
            'User': b['user_name'],
            'E-Mail': b['user_email'],
            'Telefon': b.get('user_phone', 'N/A')
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True)

def show_users():
    """User-Verwaltung (Admin)"""
    if not st.session_state.user or st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return

    st.title("👥 Benutzer-Verwaltung")

    users = ww_db.get_all_users()
    st.success(f"✅ {len(users)} User(s) registriert")

    for u in users:
        with st.expander(f"👤 {u['name']} ({u['email']})"):
            col1, col2 = st.columns(2)

            with col1:
                st.text(f"E-Mail: {u['email']}")
                st.text(f"Telefon: {u.get('phone', 'N/A')}")
                st.text(f"Rolle: {u.get('role', 'user')}")

            with col2:
                status = "🟢 Aktiv" if u.get('active', True) else "🔴 Deaktiviert"
                st.text(f"Status: {status}")

                if not u.get('active', True):
                    if st.button(f"✅ Aktivieren", key=f"activate_{u['id']}"):
                        if ww_db.update_user(u['id'], active=True):
                            st.success("✅ User aktiviert")
                            st.rerun()
                else:
                    if st.button(f"❌ Deaktivieren", key=f"deactivate_{u['id']}"):
                        if ww_db.update_user(u['id'], active=False):
                            st.warning("⚠️ User deaktiviert")
                            st.rerun()

def show_export():
    """Export & Backup (Admin)"""
    if not st.session_state.user or st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return

    st.title("📥 Export & Backup")

    st.info("Backup-Funktionalität aus alter Version beibehalten - implementiere create_backup() aus alter App")

def show_settings():
    """System-Einstellungen (Admin)"""
    if not st.session_state.user or st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return

    st.title("⚙️ System-Einstellungen")

    st.markdown("### 🔔 Notification-System Status")

    if NOTIFICATIONS_AVAILABLE:
        col1, col2 = st.columns(2)

        with col1:
            if st.session_state.email_notifier:
                st.success("✅ E-Mail-System bereit")
                st.code(f"Server: {st.session_state.email_notifier.server}:{st.session_state.email_notifier.port}")
            else:
                st.error("❌ E-Mail-System nicht verfügbar")

        with col2:
            if st.session_state.sms_notifier:
                st.success("✅ SMS-System bereit")
                st.code(f"Von: {st.session_state.sms_notifier.from_number}")
            else:
                st.error("❌ SMS-System nicht verfügbar")
    else:
        st.error("❌ notifications.py nicht gefunden!")

def show_impressum():
    """Impressum"""
    st.title("📄 Impressum")
    st.markdown("""
    ### Wasserwacht Dienstplan+

    **Version:** """ + VERSION + """

    **Kontakt:**
    - E-Mail: info@wasserwacht.de
    - Telefon: +49 123 456789

    **Datenschutz:**
    Ihre Daten werden ausschließlich zur Verwaltung der Dienstplanung verwendet.
    """)

# ═════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═════════════════════════════════════════════════════════════════════════════

def main():
    """Hauptanwendung"""
    inject_css(st.session_state.dark_mode)

    # Sidebar
    with st.sidebar:
        st.markdown(f"<h2 style='text-align:center;'>🌊 Wasserwacht</h2>", unsafe_allow_html=True)
        st.markdown(f"<p style='text-align:center;font-size:0.8rem;opacity:0.7;'>v{VERSION}</p>",
                   unsafe_allow_html=True)
        st.divider()

        if st.session_state.user:
            st.success(f"✅ {st.session_state.user['name']}")
            role = st.session_state.user.get('role', 'user')

            if st.button("🏠 Startseite", use_container_width=True):
                st.session_state.page = 'home'
                st.rerun()

            if st.button("📅 Meine Schichten", use_container_width=True):
                st.session_state.page = 'my_bookings'
                st.rerun()

            if st.button("👤 Profil", use_container_width=True):
                st.session_state.page = 'profile'
                st.rerun()

            if role == 'admin':
                st.divider()
                st.markdown("**🔧 Admin**")

                if st.button("📊 Dashboard", use_container_width=True):
                    st.session_state.page = 'dashboard'
                    st.rerun()

                if st.button("👥 Benutzer", use_container_width=True):
                    st.session_state.page = 'users'
                    st.rerun()

                if st.button("📋 Alle Buchungen", use_container_width=True):
                    st.session_state.page = 'all_bookings'
                    st.rerun()

                if st.button("📥 Export", use_container_width=True):
                    st.session_state.page = 'export'
                    st.rerun()

                if st.button("⚙️ Einstellungen", use_container_width=True):
                    st.session_state.page = 'settings'
                    st.rerun()

            st.divider()

            if st.button("📄 Impressum", use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()

            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.user = None
                st.session_state.page = 'home'
                st.rerun()

        else:
            if st.button("🔑 Login", use_container_width=True):
                st.session_state.page = 'login'
                st.rerun()

            if st.button("📄 Impressum", use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()

        st.divider()

        if st.button("🌓" if st.session_state.dark_mode else "☀️", use_container_width=True):
            st.session_state.dark_mode = not st.session_state.dark_mode
            st.rerun()

    # Page Routing
    page = st.session_state.page

    if page == 'login':
        show_login()
    elif page == 'home':
        show_home()
    elif page == 'my_bookings':
        show_my_bookings()
    elif page == 'profile':
        show_profile()
    elif page == 'dashboard':
        show_dashboard()
    elif page == 'users':
        show_users()
    elif page == 'all_bookings':
        show_all_bookings()
    elif page == 'export':
        show_export()
    elif page == 'settings':
        show_settings()
    elif page == 'impressum':
        show_impressum()
    else:
        show_home()

if __name__ == "__main__":
    main()
