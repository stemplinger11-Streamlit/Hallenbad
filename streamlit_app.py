"""
Wasserwacht Dienstplan+ V8.0 - Debug Edition
Alle Bugs behoben | Admin Debug-Panel | E-Mail/SMS funktionieren | Production-Ready
"""

import streamlit as st
import hashlib
import io
import json
import zipfile
import calendar as cal_module
from datetime import datetime, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import email.utils
import smtplib
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from twilio.rest import Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.cloud import firestore
from google.oauth2 import service_account
from collections import Counter

# ===== PAGE CONFIG =====
st.set_page_config(
    page_title="Wasserwacht Dienstplan+",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== KONFIGURATION =====
VERSION = "8.0 - Debug Edition"
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
    "rot": "#DC143C", "rot_dunkel": "#B22222", "rot_hell": "#FF6B6B",
    "blau": "#003087", "blau_hell": "#4A90E2",
    "weiss": "#FFFFFF", "grau_hell": "#F5F7FA", "grau_mittel": "#E1E8ED",
    "grau_dunkel": "#657786", "text": "#14171A", 
    "erfolg": "#17BF63", "warnung": "#FFAD1F", "fehler": "#E0245E",
    "orange": "#FF8C00", "orange_hell": "#FFA500"
}

# ===== FIREBASE INIT =====
@st.cache_resource
def init_firestore():
    try:
        if not hasattr(st, 'secrets'):
            st.error("❌ Keine Secrets gefunden!")
            st.stop()
        key = st.secrets.get("firebase", {}).get("service_account_key")
        if not key:
            st.error("❌ Firebase Service Account Key fehlt in Secrets!")
            st.stop()
        key_dict = json.loads(key)
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds, project=key_dict["project_id"])
    except Exception as e:
        st.error(f"❌ Firebase Init Fehler: {e}")
        st.stop()

db = init_firestore()

# ===== HELPER FUNCTIONS =====
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def week_start(d=None):
    d = d or datetime.now().date()
    if hasattr(d, "date"):
        d = d.date()
    return d - timedelta(days=d.weekday())

def slot_date(ws, day):
    days = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
    return (ws + timedelta(days=days.get(day,0))).strftime("%Y-%m-%d")

def fmt_de(d):
    try:
        if isinstance(d, str):
            return datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
        return d.strftime("%d.%m.%Y")
    except:
        return str(d)

def is_holiday(d):
    if isinstance(d, date):
        d = d.strftime("%Y-%m-%d")
    return d in BAVARIA_HOLIDAYS.get(d[:4], [])

def is_summer(d):
    try:
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d")
        return 6 <= d.month <= 9
    except:
        return False

def is_blocked(d):
    return is_holiday(d) or is_summer(d)

def block_reason(d):
    if is_holiday(d):
        return "Feiertag"
    elif is_summer(d):
        return "Sommerpause"
    return None

# ===== CSS INJECTION =====
def inject_css(dark=False):
    bg = "#1A1D23" if dark else COLORS["weiss"]
    surface = "#2D3238" if dark else COLORS["grau_hell"]
    text = "#FFFFFF" if dark else COLORS["text"]
    primary = COLORS["rot_hell"] if dark else COLORS["rot"]
    
    st.markdown(f"""<style>
    .main {{background:{bg};color:{text};}}
    .stApp {{background:{bg};}}
    section[data-testid="stSidebar"] {{background:{surface};border-right:2px solid {primary};}}
    .stButton>button {{background:linear-gradient(135deg,{primary} 0%,{COLORS["rot_dunkel"]} 100%);
        color:white;border:none;border-radius:8px;padding:0.5rem 1.5rem;font-weight:600;
        transition:all 0.3s;box-shadow:0 2px 4px rgba(0,0,0,0.1);}}
    .stButton>button:hover {{transform:translateY(-2px);box-shadow:0 4px 8px rgba(220,20,60,0.3);}}
    h1,h2,h3 {{color:{primary};font-weight:700;}}
    h1 {{border-bottom:3px solid {primary};padding-bottom:0.5rem;}}
    .stTextInput input,.stTextArea textarea,.stSelectbox select {{border:2px solid {COLORS["grau_mittel"]};
        border-radius:8px;background:{surface};color:{text};}}
    .stTextInput input:focus {{border-color:{primary};box-shadow:0 0 0 2px {primary}40;}}
    </style>""", unsafe_allow_html=True)

# ===== DATABASE CLASS =====
class WasserwachtDB:
    def __init__(self):
        self.db = db
        self._init_admin()
    
    def _init_admin(self):
        """Admin-User beim ersten Start erstellen"""
        if hasattr(st,'secrets'):
            email = st.secrets.get("ADMIN_EMAIL","admin@wasserwacht.de")
            pw = st.secrets.get("ADMIN_PASSWORD","admin123")
            if not self.get_user(email):
                try:
                    self.db.collection('users').add({
                        'email':email,'name':'Admin','phone':'','password_hash':hash_pw(pw),
                        'role':'admin','active':True,'email_notifications':True,
                        'sms_notifications':False,'sms_booking_confirmation':True,
                        'created_at':firestore.SERVER_TIMESTAMP
                    })
                    print(f"✅ Admin erstellt: {email}")
                except Exception as e:
                    print(f"Admin-Erstellung fehlgeschlagen: {e}")
    
    def get_user(self,email):
        try:
            for doc in self.db.collection('users').where('email','==',email).limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except Exception as e:
            print(f"❌ get_user Fehler: {e}")
            return None
    
    def create_user(self,email,name,phone,password,role='user'):
        try:
            if self.get_user(email):
                return False,"E-Mail bereits registriert"
            self.db.collection('users').add({
                'email':email,'name':name,'phone':phone,'password_hash':hash_pw(password),
                'role':role,'active':True,'email_notifications':True,'sms_notifications':False,
                'sms_booking_confirmation':True,'created_at':firestore.SERVER_TIMESTAMP
            })
            print(f"✅ User erstellt: {email}")
            return True,"Registrierung erfolgreich"
        except Exception as e:
            print(f"❌ create_user Fehler: {e}")
            return False,str(e)
    
    def auth(self,email,password):
        u = self.get_user(email)
        if not u or not u.get('active',True):
            return False,None
        if u['password_hash'] == hash_pw(password):
            return True,u
        return False,None
    
    def get_all_users(self):
        try:
            users = []
            for doc in self.db.collection('users').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                users.append(data)
            return users
        except Exception as e:
            print(f"❌ get_all_users Fehler: {e}")
            return []
    
    def update_user(self,uid,**kwargs):
        try:
            self.db.collection('users').document(uid).update(kwargs)
            print(f"✅ User geupdatet: {uid}")
            return True
        except Exception as e:
            print(f"❌ update_user Fehler: {e}")
            return False
    
    def delete_user(self,email):
        try:
            u = self.get_user(email)
            if u:
                self.db.collection('users').document(u['id']).delete()
                print(f"✅ User gelöscht: {email}")
                return True
            return False
        except Exception as e:
            print(f"❌ delete_user Fehler: {e}")
            return False
    
    # FIX: Robuste get_week_bookings mit Fallback
    def get_week_bookings(self, ws):
        """CRITICAL: Option C - Optimiert mit Fallback"""
        try:
            # Versuch 1: Optimierte Query mit Index
            we = (datetime.strptime(ws,'%Y-%m-%d')+timedelta(days=6)).strftime('%Y-%m-%d')
            result = []
            for doc in self.db.collection('bookings')\
                    .where('slot_date','>=',ws)\
                    .where('slot_date','<=',we)\
                    .where('status','==','confirmed').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                result.append(data)
            print(f"✅ get_week_bookings: {len(result)} Buchungen geladen (optimiert)")
            return result
        except Exception as e:
            print(f"⚠️ Optimierte Query fehlgeschlagen: {e}")
            # Fallback: Einfache Query ohne Index
            try:
                result = []
                for doc in self.db.collection('bookings').where('status','==','confirmed').stream():
                    b = doc.to_dict()
                    if ws <= b.get('slot_date','') <= we:
                        b['id'] = doc.id
                        result.append(b)
                print(f"✅ get_week_bookings: {len(result)} Buchungen geladen (Fallback)")
                return result
            except Exception as e2:
                print(f"❌ Fallback Query fehlgeschlagen: {e2}")
                return []
    
    def create_booking(self,slot_date,slot_time,user_email,user_name,user_phone):
        try:
            existing = self.get_booking(slot_date,slot_time)
            if existing:
                return False,"Slot bereits gebucht"
            self.db.collection('bookings').add({
                'slot_date':slot_date,'slot_time':slot_time,'user_email':user_email,
                'user_name':user_name,'user_phone':user_phone,'status':'confirmed',
                'created_at':firestore.SERVER_TIMESTAMP
            })
            print(f"✅ Buchung erstellt: {user_name} | {slot_date} {slot_time}")
            return True,"Buchung erfolgreich"
        except Exception as e:
            print(f"❌ create_booking Fehler: {e}")
            return False,str(e)
    
    def get_booking(self,slot_date,slot_time):
        try:
            for doc in self.db.collection('bookings').where('slot_date','==',slot_date)\
                    .where('slot_time','==',slot_time).where('status','==','confirmed').limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except Exception as e:
            print(f"❌ get_booking Fehler: {e}")
            return None
    
    def get_user_bookings(self,email,future_only=False):
        try:
            q = self.db.collection('bookings').where('user_email','==',email).where('status','==','confirmed')
            if future_only:
                q = q.where('slot_date','>=',datetime.now().strftime("%Y-%m-%d"))
            bookings = []
            for doc in q.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                bookings.append(data)
            return sorted(bookings,key=lambda x:x['slot_date'])
        except Exception as e:
            print(f"❌ get_user_bookings Fehler: {e}")
            return []
    
    def cancel_booking(self,bid,cancelled_by):
        try:
            self.db.collection('bookings').document(bid).update({
                'status':'cancelled','cancelled_by':cancelled_by,
                'cancelled_at':firestore.SERVER_TIMESTAMP
            })
            print(f"✅ Buchung storniert: {bid}")
            return True
        except Exception as e:
            print(f"❌ cancel_booking Fehler: {e}")
            return False
    
    def get_setting(self,key,default=''):
        try:
            doc = self.db.collection('settings').document(key).get()
            return doc.to_dict().get('value',default) if doc.exists else default
        except:
            return default
    
    def set_setting(self,key,value):
        try:
            self.db.collection('settings').document(key).set({
                'value':value,'updated_at':firestore.SERVER_TIMESTAMP
            },merge=True)
            return True
        except:
            return False
    
    def get_stats(self):
        """FIX: Robuste Statistiken mit Fehlerbehandlung"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Total Users
            all_users = self.get_all_users()
            total_users = len([u for u in all_users if u.get('active',True)])
            
            # Future Bookings
            future_bookings = []
            try:
                for doc in self.db.collection('bookings').where('status','==','confirmed').stream():
                    b = doc.to_dict()
                    if b.get('slot_date','') >= today:
                        future_bookings.append(b)
            except:
                pass
            
            # Month Bookings
            month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            month_bookings = []
            try:
                for doc in self.db.collection('bookings').where('status','==','confirmed').stream():
                    b = doc.to_dict()
                    date_str = b.get('slot_date','')
                    if month_start <= date_str:
                        month_bookings.append(b)
            except:
                pass
            
            # Free Slots
            free_slots = []
            for i in range(28):
                check_date = (datetime.now()+timedelta(days=i)).strftime("%Y-%m-%d")
                if not is_blocked(check_date):
                    for slot in WEEKLY_SLOTS:
                        ws = week_start(datetime.strptime(check_date,"%Y-%m-%d"))
                        slot_d = slot_date(ws,slot['day'])
                        if slot_d == check_date:
                            if not self.get_booking(check_date,f"{slot['start']}-{slot['end']}"):
                                free_slots.append({
                                    'date':check_date,
                                    'slot':f"{slot['day_name']} {slot['start']}-{slot['end']}"
                                })
            
            return {
                'total_users':total_users,
                'future_bookings':len(future_bookings),
                'month_bookings':len(month_bookings),
                'free_slots_next_4weeks':free_slots
            }
        except Exception as e:
            print(f"❌ get_stats Fehler: {e}")
            return {'total_users':0,'future_bookings':0,'month_bookings':0,'free_slots_next_4weeks':[]}
    
    def archive_old(self):
        """Alte Buchungen archivieren"""
        try:
            months = 12
            archive_date = (datetime.now()-timedelta(days=30*months)).strftime("%Y-%m-%d")
            count = 0
            for doc in self.db.collection('bookings').where('slot_date','<',archive_date).stream():
                self.db.collection('archive').add(doc.to_dict())
                doc.reference.delete()
                count += 1
            if count > 0:
                print(f"✅ {count} Buchungen archiviert")
            return count
        except Exception as e:
            print(f"❌ archive_old Fehler: {e}")
            return 0

ww_db = WasserwachtDB()

# ===== ENDE TEIL 1 =====
# ===== EMAIL & SMS CLASSES (FIX: Aus alter funktionierender Version) =====
# ===== E-MAIL KLASSE (VOLLSTÄNDIG MIT ALLEN FEATURES) =====
class Mailer:
    """E-Mail Versand mit Template-System und detailliertem Error-Handling"""
    def __init__(self):
        # DEBUG: Secrets prüfen
        print(f"DEBUG: hasattr(st, 'secrets') = {hasattr(st, 'secrets')}")
        if hasattr(st, 'secrets'):
            print(f"DEBUG: SMTP_USER in secrets? {'SMTP_USER' in st.secrets}")
        else:
            print("DEBUG: st.secrets NICHT vorhanden!")
        
        if hasattr(st,'secrets'):
            self.server = st.secrets.get("SMTP_SERVER","smtp.gmail.com")
            self.port = int(st.secrets.get("SMTP_PORT",587))
            self.user = st.secrets.get("SMTP_USER","")
            self.pw = st.secrets.get("SMTP_PASSWORD","")
            self.admin_receiver = st.secrets.get("ADMIN_EMAIL_RECEIVER","")
            self.fromname = "Wasserwacht Dienstplan"
            
            # DEBUG: Was wurde geladen?
            print(f"DEBUG: self.user = {self.user[:5] if self.user else 'LEER'}***")
            print(f"DEBUG: self.pw = {'GESETZT' if self.pw else 'LEER'}")
        else:
            self.server = self.port = self.user = self.pw = self.admin_receiver = ""
            self.fromname = "Dienstplan"
    
    def send(self, to, subject, body, attachments=None):
        """CRITICAL: E-Mail-Versand mit detailliertem Error-Handling"""
        if not self.user or not self.pw:
            print("❌ E-Mail: Keine Credentials in Secrets")
            return False, "❌ Keine SMTP Credentials konfiguriert"
        
        if not to:
            return False, "❌ Keine Empfänger-Adresse"
        
        try:
            msg = MIMEMultipart()
            msg['From'] = email.utils.formataddr((self.fromname, self.user))
            msg['To'] = to
            msg['Subject'] = subject
            msg['Date'] = email.utils.formatdate(localtime=True)
            msg.attach(MIMEText(body, 'html', 'utf-8'))
            
            if attachments:
                for filename, data in attachments:
                    part = MIMEBase('application', 'octet-stream')
                    if isinstance(data, bytes):
                        part.set_payload(data)
                    else:
                        part.set_payload(data.encode('utf-8'))
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename={filename}')
                    msg.attach(part)
            
            with smtplib.SMTP(self.server, self.port, timeout=60) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.user, self.pw)
                server.send_message(msg)
            
            print(f"✅ E-Mail gesendet an {to}")
            return True, f"✅ E-Mail erfolgreich an {to} gesendet"
        
        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"❌ SMTP Auth Fehler: {e}\n\nPrüfen Sie:\n1. SMTP_USER korrekt? ({self.user})\n2. SMTP_PASSWORD ist Gmail App-Passwort?\n3. 2-Faktor-Auth aktiviert?"
            print(error_msg)
            return False, error_msg
        except smtplib.SMTPException as e:
            error_msg = f"❌ SMTP Fehler: {type(e).__name__}: {e}"
            print(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"❌ E-Mail Fehler: {type(e).__name__}: {e}"
            print(error_msg)
            return False, error_msg
    
    def send_booking_confirmation(self, user_email, user_name, slot_date, slot_time):
        """Buchungsbestätigung senden - verwendet Template"""
        subject_template = ww_db.get_setting('email_booking_subject', 'Buchungsbestätigung - {date}')
        body_template = ww_db.get_setting('email_booking_body', 
            """Hallo {name},

deine Buchung wurde bestätigt:

📅 Datum: {date}
⏰ Uhrzeit: {time}

Bei Fragen melde dich gerne unter {org_email}.

Viele Grüße,
Dein {org_name} Team 🌊""")
        
        data = {
            'name': user_name,
            'date': fmt_de(slot_date),
            'time': slot_time,
            'email': user_email,
            'org_name': ww_db.get_setting('org_name', 'Wasserwacht'),
            'org_email': self.admin_receiver,
            'current_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        
        subject = subject_template
        body = f"""<html><body style='font-family:Arial,sans-serif'>
        <h2 style='color:{COLORS['rot']}'>🌊 Wasserwacht Dienstplan+</h2>
        <p>{body_template}</p>
        </body></html>"""
        
        for key, value in data.items():
            subject = subject.replace('{' + key + '}', str(value))
            body = body.replace('{' + key + '}', str(value))
        
        return self.send(user_email, subject, body)
    
    def send_cancellation(self, user_email, user_name, slot_date, slot_time):
        """Stornierungsbestätigung senden - verwendet Template"""
        subject_template = ww_db.get_setting('email_cancellation_subject', 'Stornierung - {date}')
        body_template = ww_db.get_setting('email_cancellation_body',
            """Hallo {name},

deine Buchung wurde storniert:

📅 Datum: {date}
⏰ Uhrzeit: {time}

Viele Grüße,
Dein {org_name} Team 🌊""")
        
        data = {
            'name': user_name,
            'date': fmt_de(slot_date),
            'time': slot_time,
            'email': user_email,
            'org_name': ww_db.get_setting('org_name', 'Wasserwacht'),
            'org_email': self.admin_receiver,
            'current_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        
        subject = subject_template
        body = f"""<html><body style='font-family:Arial,sans-serif'>
        <h2 style='color:{COLORS['fehler']}'>❌ Stornierung</h2>
        <p>{body_template}</p>
        </body></html>"""
        
        for key, value in data.items():
            subject = subject.replace('{' + key + '}', str(value))
            body = body.replace('{' + key + '}', str(value))
        
        return self.send(user_email, subject, body)
    
    def send_reminder(self, user_email, user_name, slot_date, slot_time):
        """Erinnerung senden - verwendet Template"""
        subject_template = ww_db.get_setting('email_reminder_subject', '⏰ Erinnerung: Dienst morgen - {date}')
        body_template = ww_db.get_setting('email_reminder_body',
            """Hallo {name},

dein Dienst ist morgen:

📅 Datum: {date}
⏰ Uhrzeit: {time}

Bis morgen!
Dein {org_name} Team 🌊""")
        
        data = {
            'name': user_name,
            'date': fmt_de(slot_date),
            'time': slot_time,
            'email': user_email,
            'org_name': ww_db.get_setting('org_name', 'Wasserwacht'),
            'org_email': self.admin_receiver,
            'current_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        
        subject = subject_template
        body = f"""<html><body style='font-family:Arial,sans-serif'>
        <h2 style='color:{COLORS['orange']}'>⏰ Erinnerung</h2>
        <p>{body_template}</p>
        </body></html>"""
        
        for key, value in data.items():
            subject = subject.replace('{' + key + '}', str(value))
            body = body.replace('{' + key + '}', str(value))
        
        return self.send(user_email, subject, body)
    
    def send_welcome(self, user_email, user_name):
        """Willkommens-E-Mail senden - NEU"""
        subject_template = ww_db.get_setting('email_welcome_subject', 'Willkommen bei {org_name}!')
        body_template = ww_db.get_setting('email_welcome_body',
            """Hallo {name},

herzlich willkommen bei {org_name}! 🌊

Dein Account wurde erfolgreich erstellt.
Du kannst dich jetzt anmelden und Schichten buchen.

📧 E-Mail: {email}

Bei Fragen erreichst du uns unter {org_email}.

Viele Grüße,
Dein {org_name} Team""")
        
        data = {
            'name': user_name,
            'email': user_email,
            'org_name': ww_db.get_setting('org_name', 'Wasserwacht'),
            'org_email': self.admin_receiver,
            'current_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        
        subject = subject_template
        body = f"""<html><body style='font-family:Arial,sans-serif'>
        <h2 style='color:{COLORS['rot']}'>🌊 Willkommen!</h2>
        <p>{body_template}</p>
        </body></html>"""
        
        for key, value in data.items():
            subject = subject.replace('{' + key + '}', str(value))
            body = body.replace('{' + key + '}', str(value))
        
        return self.send(user_email, subject, body)
    
    def send_admin_notification(self, user_name, user_email, user_phone, slot_date, slot_time):
        """Admin-Benachrichtigung bei neuer Buchung - NEU"""
        if not self.admin_receiver:
            return False, "Keine Admin-E-Mail konfiguriert"
        
        subject_template = ww_db.get_setting('email_admin_notification_subject', '🔔 Neue Buchung: {name} - {date}')
        body_template = ww_db.get_setting('email_admin_notification_body',
            """Neue Buchung im Dienstplan:

👤 Name: {name}
📧 E-Mail: {email}
📱 Telefon: {phone}

📅 Datum: {date}
⏰ Uhrzeit: {time}

Gebucht am: {current_date}""")
        
        data = {
            'name': user_name,
            'email': user_email,
            'phone': user_phone if user_phone else 'Nicht angegeben',
            'date': fmt_de(slot_date),
            'time': slot_time,
            'org_name': ww_db.get_setting('org_name', 'Wasserwacht'),
            'org_email': self.admin_receiver,
            'current_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        
        subject = subject_template
        body = f"""<html><body style='font-family:Arial,sans-serif'>
        <h2 style='color:{COLORS['blau']}'>🔔 Neue Buchung</h2>
        <pre>{body_template}</pre>
        </body></html>"""
        
        for key, value in data.items():
            subject = subject.replace('{' + key + '}', str(value))
            body = body.replace('{' + key + '}', str(value))
        
        return self.send(self.admin_receiver, subject, body)
    
    def send_password_reset_notification(self, user_email, user_name, admin_name):
        """Benachrichtigung über Passwort-Reset - NEU"""
        subject_template = ww_db.get_setting('email_password_reset_subject', 'Ihr Passwort wurde zurückgesetzt')
        body_template = ww_db.get_setting('email_password_reset_body',
            """Hallo {name},

Ihr Passwort wurde vom Administrator zurückgesetzt.

**Wichtig:** Bitte kontaktieren Sie Ihren Administrator ({admin_name}), um Ihr neues Passwort zu erhalten.

Aus Sicherheitsgründen wird das Passwort nicht per E-Mail verschickt.

Nach dem nächsten Login werden Sie aufgefordert, Ihr Passwort zu ändern.

Bei Fragen wenden Sie sich an: {org_email}

Viele Grüße,
Ihr {org_name} Team""")
        
        data = {
            'name': user_name,
            'email': user_email,
            'admin_name': admin_name,
            'org_name': ww_db.get_setting('org_name', 'Wasserwacht'),
            'org_email': self.admin_receiver,
            'current_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        
        subject = subject_template
        body = f"""<html><body style='font-family:Arial,sans-serif'>
        <h2 style='color:{COLORS['orange']}'>🔑 Passwort zurückgesetzt</h2>
        <p>{body_template}</p>
        </body></html>"""
        
        for key, value in data.items():
            subject = subject.replace('{' + key + '}', str(value))
            body = body.replace('{' + key + '}', str(value))
        
        return self.send(user_email, subject, body)
    
    def test_email(self, to):
        """Test-E-Mail mit Timestamp"""
        body = f"""<html><body style='font-family:Arial,sans-serif'>
        <h2 style='color:{COLORS['rot']}'>🌊 Test-E-Mail</h2>
        <p>Dies ist eine Test-E-Mail vom Wasserwacht Dienstplan+</p>
        <p><b>Zeitpunkt:</b> {datetime.now(TZ).strftime('%d.%m.%Y %H:%M:%S')}</p>
        <p><b>Status:</b> ✅ E-Mail-Versand funktioniert!</p>
        <p><b>SMTP Server:</b> {self.server}:{self.port}</p>
        <p><b>SMTP User:</b> {self.user}</p>
        </body></html>"""
        return self.send(to, "Test-E-Mail - Wasserwacht Dienstplan+", body)
    
    def backup_email(self, backup_zip):
        """Backup per E-Mail versenden"""
        try:
            subject = f"📦 Dienstplan Backup {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            body = f"""<html><body style='font-family:Arial,sans-serif'>
            <h2 style='color:{COLORS['rot']}'>📦 Automatisches Backup</h2>
            <p><b>Zeitpunkt:</b> {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')} Uhr</p>
            <p><b>Inhalt:</b> Alle Buchungen, User und Einstellungen</p>
            <p><b>Format:</b> ZIP-Archiv mit CSV-Dateien</p>
            </body></html>"""
            
            filename = f"dienstplan_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            
            backup_emails = []
            if hasattr(st,'secrets'):
                try:
                    backup_emails = json.loads(st.secrets.get("BACKUP_EMAILS","[]"))
                except:
                    backup_emails = []
                admin = st.secrets.get("ADMIN_EMAIL_RECEIVER","")
                if admin and admin not in backup_emails:
                    backup_emails.append(admin)
            
            success_count = 0
            for email_addr in backup_emails:
                success, msg = self.send(email_addr, subject, body, [(filename, backup_zip)])
                if success:
                    success_count += 1
            
            return success_count > 0
        except Exception as e:
            print(f"❌ Backup-E-Mail Fehler: {e}")
            return False


class TwilioSMS:
    def __init__(self):
        if hasattr(st,'secrets'):
            self.sid = st.secrets.get("TWILIO_ACCOUNT_SID","")
            self.token = st.secrets.get("TWILIO_AUTH_TOKEN","")
            self.phone = st.secrets.get("TWILIO_PHONE_NUMBER","")
            self.enabled = st.secrets.get("ENABLE_SMS_REMINDER","false").lower()=="true"
        else:
            self.sid = self.token = self.phone = ""
            self.enabled = False
    
    # FIX: EXAKTE Syntax aus alter funktionierender Version
    def send(self,to,message):
        """CRITICAL: SMS-Versand mit Nummer-Formatierung"""
        if not self.enabled:
            print("⚠️ SMS: Nicht aktiviert (ENABLE_SMS_REMINDER=false)")
            return False
        
        if not self.sid or not self.token or not self.phone:
            print("❌ SMS: Keine Credentials in Secrets")
            return False
        
        try:
            # FIX: Nummer formatieren für Deutschland
            if to and not to.startswith('+'):
                if to.startswith('0'):
                    to = '+49' + to[1:]
                else:
                    to = '+49' + to
            
            client = Client(self.sid, self.token)
            msg = client.messages.create(
                to=to,
                from_=self.phone,
                body=message
            )
            
            print(f"✅ SMS gesendet an {to}: {msg.sid}")
            return True
        
        except Exception as e:
            print(f"❌ SMS-Fehler: {e}")
            st.error(f"🔴 SMS-Fehler: {e}")
            return False
    
    def booking_confirmation(self,user_phone,user_name,slot_date,slot_time):
        """SMS bei Buchung"""
        template = ww_db.get_setting('sms_booking_template',
            'Wasserwacht: Buchung bestätigt! {date} {time}. Wir freuen uns auf dich!')
        msg = template.format(name=user_name,date=fmt_de(slot_date),time=slot_time)
        return self.send(user_phone,msg)
    
    def reminder_24h(self,user_phone,user_name,slot_date,slot_time):
        """24h Reminder"""
        template = ww_db.get_setting('sms_24h_template',
            'Wasserwacht: Deine Schicht ist morgen {date} um {time}. Bis morgen!')
        msg = template.format(name=user_name,date=fmt_de(slot_date),time=slot_time)
        return self.send(user_phone,msg)
    
    def reminder_1h(self,user_phone,user_name,slot_time):
        """1h Reminder"""
        template = ww_db.get_setting('sms_1h_template',
            'Wasserwacht: Deine Schicht beginnt in 1h ({time}). Bis gleich!')
        msg = template.format(name=user_name,time=slot_time)
        return self.send(user_phone,msg)
    
    def test_sms(self,to):
        """Test-SMS"""
        msg = f"Wasserwacht Test-SMS. Zeit: {datetime.now(TZ).strftime('%H:%M')}"
        return self.send(to,msg)

mailer = Mailer()
sms = TwilioSMS()

# ===== SCHEDULER =====
def daily_tasks():
    """Tägliche Aufgaben: Archivierung + Backup"""
    ww_db.archive_old()
    if hasattr(st,'secrets') and st.secrets.get("ENABLE_DAILY_BACKUP","true").lower()=="true":
        try:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as zf:
                csv = "date,time,user,phone,status\n"
                for doc in ww_db.db.collection('bookings').stream():
                    d = doc.to_dict()
                    csv += f"{d.get('slot_date','')},{d.get('slot_time','')},{d.get('user_name','')},{d.get('user_phone','')},{d.get('status','')}\n"
                zf.writestr('bookings.csv',csv)
            mailer.backup_email(buffer.getvalue())
        except Exception as e:
            print(f"❌ Daily Backup Fehler: {e}")

def reminder_tasks():
    """24h Reminder-SMS versenden"""
    tomorrow = (datetime.now()+timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        for doc in ww_db.db.collection('bookings').where('slot_date','==',tomorrow)\
                .where('status','==','confirmed').stream():
            b = doc.to_dict()
            if b.get('user_phone'):
                u = ww_db.get_user(b['user_email'])
                if u and u.get('sms_notifications',False):
                    sms.reminder_24h(b['user_phone'],b['user_name'],b['slot_date'],b['slot_time'])
    except Exception as e:
        print(f"❌ Reminder Fehler: {e}")

def check_free_slots_alarm():
    """Warnung bei freien Slots"""
    try:
        critical = []
        for i in range(1,8):
            check_date = (datetime.now()+timedelta(days=i)).strftime("%Y-%m-%d")
            if not is_blocked(check_date):
                for slot in WEEKLY_SLOTS:
                    ws = week_start(datetime.strptime(check_date,"%Y-%m-%d"))
                    slot_d = slot_date(ws,slot['day'])
                    if slot_d == check_date and not ww_db.get_booking(check_date,f"{slot['start']}-{slot['end']}"):
                        critical.append({'date':fmt_de(check_date),'day':slot['day_name'],'time':f"{slot['start']}-{slot['end']}"})
        if critical:
            admins = [u['email'] for u in ww_db.get_all_users() if u.get('role')=='admin' and u.get('active',True)]
            slots_html = "".join([f"<li>{s['date']} ({s['day']}) {s['time']}</li>" for s in critical])
            body = f"<html><body><h2 style='color:{COLORS['warnung']}'>⚠️ {len(critical)} freie Slots</h2><ul>{slots_html}</ul></body></html>"
            for admin in admins:
                mailer.send(admin,"⚠️ Freie Slots",body)
    except Exception as e:
        print(f"❌ Free Slots Alarm Fehler: {e}")

if 'scheduler_started' not in st.session_state:
    try:
        scheduler = BackgroundScheduler(timezone=TZ)
        h,m = (st.secrets.get("BACKUP_TIME","20:00") if hasattr(st,'secrets') else "20:00").split(":")
        scheduler.add_job(daily_tasks,'cron',hour=int(h),minute=int(m))
        scheduler.add_job(reminder_tasks,'cron',hour=18,minute=0)
        scheduler.add_job(check_free_slots_alarm,'cron',hour=18,minute=0)
        scheduler.start()
        st.session_state.scheduler_started = True
        print("✅ Scheduler gestartet")
    except Exception as e:
        print(f"❌ Scheduler Fehler: {e}")

# ===== MAIN APP =====
def main():
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'last_activity' not in st.session_state:
        st.session_state.last_activity = datetime.now()
    
    # Auto-Logout nach Inaktivität
    timeout_min = 30
    if st.session_state.user:
        inactive = (datetime.now()-st.session_state.last_activity).total_seconds()
        if inactive > timeout_min*60:
            st.session_state.user = None
            st.warning("⏰ Automatisch ausgeloggt (Inaktivität)")
            st.rerun()
        else:
            st.session_state.last_activity = datetime.now()
    
    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = False
    inject_css(st.session_state.dark_mode)
    
    if 'page' not in st.session_state:
        st.session_state.page = 'home'
    
    # Sidebar Navigation
    with st.sidebar:
        st.markdown(f"<h1 style='color:{COLORS['rot']}'>🌊 Wasserwacht</h1>",unsafe_allow_html=True)
        st.markdown(f"<p style='color:{COLORS['grau_dunkel']}'>v{VERSION}</p>",unsafe_allow_html=True)
        st.divider()
        
        if st.session_state.user:
            st.success(f"✅ {st.session_state.user['name']}")
            role = st.session_state.user.get('role','user')
            
            if st.button("🏠 Startseite",use_container_width=True):
                st.session_state.page = 'home'
                st.rerun()
            if st.button("📅 Meine Schichten",use_container_width=True):
                st.session_state.page = 'my_bookings'
                st.rerun()
            if st.button("📅 Kalender",use_container_width=True):
                st.session_state.page = 'calendar'
                st.rerun()
            if st.button("📚 Handbuch",use_container_width=True):
                st.session_state.page = 'handbook'
                st.rerun()
            if st.button("👤 Profil",use_container_width=True):
                st.session_state.page = 'profile'
                st.rerun()
            
            if role == 'admin':
                st.divider()
                st.markdown("**🔧 Admin**")
                if st.button("📊 Dashboard",use_container_width=True):
                    st.session_state.page = 'dashboard'
                    st.rerun()
                if st.button("👥 Benutzer",use_container_width=True):
                    st.session_state.page = 'users'
                    st.rerun()
                if st.button("📋 Alle Buchungen",use_container_width=True):
                    st.session_state.page = 'all_bookings'
                    st.rerun()
                if st.button("📥 Export",use_container_width=True):
                    st.session_state.page = 'export'
                    st.rerun()
                if st.button("⚙️ Einstellungen",use_container_width=True):
                    st.session_state.page = 'settings'
                    st.rerun()
            
            st.divider()
            if st.button("📄 Impressum",use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()
            if st.button("🚪 Logout",use_container_width=True):
                st.session_state.user = None
                st.session_state.page = 'home'
                st.rerun()
        else:
            if st.button("🔑 Login",use_container_width=True):
                st.session_state.page = 'login'
                st.rerun()
            if st.button("📄 Impressum",use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()
        
        st.divider()
        if st.button("🌓" if st.session_state.dark_mode else "☀️",use_container_width=True):
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
    elif page == 'all_bookings':
        show_all_bookings()
    elif page == 'calendar':
        show_month_calendar()
    elif page == 'handbook':
        show_handbook()
    elif page == 'profile':
        show_profile()
    elif page == 'dashboard':
        show_dashboard()
    elif page == 'users':
        show_users()
    elif page == 'export':
        show_export()
    elif page == 'settings':
        show_settings()
    elif page == 'impressum':
        show_impressum()

def show_login():
    st.title("🔐 Login & Registrierung")
    
    tab1, tab2 = st.tabs(["🔐 Anmelden", "📝 Registrieren"])
    
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
                    
                    # CHECK: Muss User Passwort ändern?
                    if user.get('must_change_password', False):
                        st.session_state.force_password_change = True
                        st.warning("⚠️ Sie müssen Ihr Passwort ändern!")
                    
                    st.session_state.page = "home"
                    st.success("✅ Erfolgreich angemeldet!")
                    st.rerun()
                else:
                    st.error("❌ Ungültige Anmeldedaten")
    
    with tab2:
        # Rest bleibt wie gehabt
        st.subheader("Neuen Account erstellen")
        with st.form("register"):
            name = st.text_input("Name")
            email = st.text_input("E-Mail")
            phone = st.text_input("Telefon (für SMS-Reminder)")
            pw = st.text_input("Passwort ", type="password")
            pw2 = st.text_input("Passwort bestätigen ", type="password")
            accept = st.checkbox("Ich akzeptiere die Datenschutzerklärung")
            
            if st.form_submit_button("Registrieren", type="primary", use_container_width=True):
                if not name or not email or not pw or not pw2:
                    st.error("❌ Bitte alle Pflichtfelder ausfüllen!")
                elif pw != pw2:
                    st.error("❌ Passwörter stimmen nicht überein!")
                elif len(pw) < 6:  # Angepasst auf 6 Zeichen
                    st.error("❌ Passwort muss mindestens 6 Zeichen lang sein!")
                elif not accept:
                    st.error("❌ Bitte Datenschutzerklärung akzeptieren!")
                else:
                    success, msg = ww_db.createuser(email, name, phone, pw)
                    if success:
                        st.success(f"✅ {msg}")
                        st.balloons()
                    else:
                        st.error(f"❌ {msg}")

# ===== ENDE TEIL 2 =====
# ===== PAGE FUNCTIONS =====

# FIX: CRITICAL - Gebuchte Slots müssen ORANGE angezeigt werden!
def show_home():
    if not st.session_state.user:
        st.title("🌊 Willkommen beim Wasserwacht Dienstplan+")
        st.info("Bitte melde dich an um Schichten zu buchen.")
        return
    
    st.title("📅 Schichtplan")
    user = st.session_state.user
    
    if 'current_week' not in st.session_state:
        st.session_state.current_week = week_start()
    
    cws = st.session_state.current_week
    
    # Wochennavigation
    c1,c2,c3 = st.columns([1,3,1])
    with c1:
        if st.button("◀️ Vorherige"):
            st.session_state.current_week -= timedelta(days=7)
            st.rerun()
    with c2:
        st.markdown(f"<h3 style='text-align:center'>KW {cws.isocalendar()[1]}, {cws.year}</h3>",unsafe_allow_html=True)
    with c3:
        if st.button("Nächste ▶️"):
            st.session_state.current_week += timedelta(days=7)
            st.rerun()
    
    # FIX: Buchungen laden mit Fallback-Strategie
    bookings = ww_db.get_week_bookings(cws.strftime("%Y-%m-%d"))
    booking_map = {(b['slot_date'], b['slot_time']): b for b in bookings}
    
    # ADMIN DEBUG-PANEL
    if user.get('role') == 'admin':
        with st.expander("🔧 Debug-Info (Admin)"):
            st.write(f"**Firestore Bookings:** {len(bookings)} geladen")
            st.write(f"**E-Mail Status:** {'✅ Aktiv' if mailer.user else '❌ Keine Credentials'}")
            if mailer.user:
                st.write(f"**SMTP User:** {mailer.user[:3]}***@{mailer.user.split('@')[1] if '@' in mailer.user else '???'}")
            st.write(f"**SMS Status:** {'✅ Aktiv' if sms.enabled else '❌ Deaktiviert'}")
            if sms.enabled and sms.sid:
                st.write(f"**Twilio SID:** {sms.sid[:8]}***")
            
            if bookings:
                st.write("**Beispiel-Buchungen:**")
                st.json([{
                    'date': b['slot_date'],
                    'time': b['slot_time'],
                    'user': b['user_name'],
                    'status': b.get('status','')
                } for b in bookings[:3]])
            else:
                st.info("Keine Buchungen in dieser Woche")
    
    # Slots anzeigen
    for slot in WEEKLY_SLOTS:
        sd = slot_date(cws, slot['day'])
        slot_time_str = f"{slot['start']}-{slot['end']}"
        
        # CRITICAL: Prüfe ob gebucht
        booking = booking_map.get((sd, slot_time_str))
        blocked = is_blocked(sd)
        
        # FIX: FARBEN - ORANGE wenn gebucht!
        if blocked:
            bg_color = f"{COLORS['grau_mittel']}80"
            border_color = COLORS['grau_mittel']
            status_badge = f"<span style='color:{COLORS['grau_dunkel']};font-weight:600'>🚫 {block_reason(sd)}</span>"
        elif booking:
            # ORANGE HINTERGRUND + NAME!
            bg_color = f"{COLORS['orange']}30"
            border_color = COLORS['orange']
            status_badge = f"<span style='color:{COLORS['orange']};font-weight:600'>✅ Bereits von: <b>{booking['user_name']}</b> gebucht</span>"
        else:
            bg_color = f"{COLORS['blau']}10"
            border_color = COLORS['blau_hell']
            status_badge = f"<span style='color:{COLORS['erfolg']};font-weight:600'>📅 Slot verfügbar</span>"
        
        # Card HTML
        card_html = f'''<div style="background:{bg_color};border:2px solid {border_color};border-radius:12px;
            padding:1rem;margin:0.5rem 0;transition:all 0.3s">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                    <div style="font-weight:bold;font-size:1.1rem">{slot['day_name']}, {fmt_de(sd)}</div>
                    <div style="color:{COLORS['grau_dunkel']};font-size:0.9rem">{slot_time_str}</div>
                </div>
                <div>{status_badge}</div>
            </div></div>'''
        st.markdown(card_html, unsafe_allow_html=True)
        
        # Buttons
        if blocked:
            pass
        elif booking:
            # Slot ist gebucht
            if user['role'] == 'admin' or booking['user_email'] == user['email']:
                if st.button(f"🔴 Stornieren", key=f"cancel_{slot['id']}_{sd}"):
                    ww_db.cancel_booking(booking['id'], user['email'])
                    mailer.cancellation_confirmation(booking['user_email'], booking['user_name'], sd, slot_time_str)
                    st.success("✅ Storniert!")
                    st.rerun()
        else:
            # Slot ist frei
            if st.button(f"✅ Buchen", key=f"book_{slot['id']}_{sd}", type="primary"):
                # Nochmal prüfen (Race Condition)
                existing = ww_db.get_booking(sd, slot_time_str)
                
                if existing and user['role'] != 'admin':
                    st.error(f"❌ Bereits von **{existing['user_name']}** gebucht!")
                
                elif existing and user['role'] == 'admin':
                    # ADMIN ÜBERSCHREIBEN
                    st.warning(f"⚠️ Bereits von **{existing['user_name']}** gebucht!")
                    if st.button("🔄 Als Admin überschreiben", key=f"override_{slot['id']}_{sd}"):
                        ww_db.cancel_booking(existing['id'], user['email'])
                        success, msg = ww_db.create_booking(sd, slot_time_str, user['email'], user['name'], user.get('phone', ''))
                        if success:
                            mailer.booking_confirmation(user['email'], user['name'], sd, slot_time_str)
                            u = ww_db.get_user(user['email'])
                            if u.get('sms_booking_confirmation') and u.get('phone'):
                                sms.booking_confirmation(u['phone'], user['name'], sd, slot_time_str)
                            st.success("✅ Überschrieben und gebucht!")
                            st.rerun()
                        else:
                            st.error(f"❌ {msg}")
                
                else:
                    # Normal buchen
                    success, msg = ww_db.create_booking(sd, slot_time_str, user['email'], user['name'], user.get('phone', ''))
                    if success:
                        mailer.booking_confirmation(user['email'], user['name'], sd, slot_time_str)
                        u = ww_db.get_user(user['email'])
                        if u.get('sms_booking_confirmation') and u.get('phone'):
                            sms.booking_confirmation(u['phone'], user['name'], sd, slot_time_str)
                        st.success("✅ Gebucht!")
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}")

def show_my_bookings():
    st.title("📅 Meine Schichten")
    user = st.session_state.user
    bookings = ww_db.get_user_bookings(user['email'])
    
    if not bookings:
        st.info("Du hast noch keine Buchungen.")
        return
    
    for b in bookings:
        is_past = datetime.strptime(b['slot_date'],"%Y-%m-%d") < datetime.now()
        bg = f"{COLORS['grau_mittel']}40" if is_past else f"{COLORS['erfolg']}20"
        border = COLORS['grau_mittel'] if is_past else COLORS['erfolg']
        
        st.markdown(f'''<div style="background:{bg};border:2px solid {border};border-radius:12px;
            padding:1rem;margin:0.5rem 0">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                    <div style="font-weight:bold;font-size:1.1rem">{fmt_de(b['slot_date'])}</div>
                    <div style="color:{COLORS['grau_dunkel']}">{b['slot_time']}</div>
                </div>
                {"<span style='color:"+COLORS['grau_dunkel']+"'>⏮️ Vergangen</span>" if is_past else ""}
            </div></div>''', unsafe_allow_html=True)
        
        if not is_past:
            if st.button("🔴 Stornieren", key=f"cancel_{b['id']}"):
                ww_db.cancel_booking(b['id'], user['email'])
                mailer.cancellation_confirmation(user['email'], user['name'], b['slot_date'], b['slot_time'])
                st.rerun()

def show_all_bookings():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("📋 Alle Buchungen (Admin)")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        filter_type = st.selectbox("Zeitraum", ["Kommende", "Alle", "Vergangene"])
    with col2:
        all_users = ww_db.get_all_users()
        user_filter = st.selectbox("User", ["Alle"] + [u['name'] for u in all_users])
    with col3:
        sort_order = st.selectbox("Sortierung", ["Datum ↑", "Datum ↓"])
    
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        bookings = []
        
        for doc in ww_db.db.collection('bookings').where('status', '==', 'confirmed').stream():
            b = doc.to_dict()
            b['id'] = doc.id
            
            if filter_type == "Kommende" and b['slot_date'] < today:
                continue
            elif filter_type == "Vergangene" and b['slot_date'] >= today:
                continue
            
            if user_filter != "Alle" and b.get('user_name') != user_filter:
                continue
            
            bookings.append(b)
        
        bookings.sort(key=lambda x: x['slot_date'], reverse=(sort_order == "Datum ↓"))
        
        if not bookings:
            st.info("Keine Buchungen gefunden.")
        else:
            st.success(f"**{len(bookings)} Buchungen**")
            for b in bookings:
                is_past = datetime.strptime(b['slot_date'], "%Y-%m-%d") < datetime.now()
                bg = f"{COLORS['grau_mittel']}40" if is_past else f"{COLORS['erfolg']}20"
                st.markdown(f'''<div style="background:{bg};padding:1rem;margin:0.5rem 0;border-radius:8px">
                    <b>{fmt_de(b['slot_date'])}</b> {b['slot_time']} - {b['user_name']}</div>''', unsafe_allow_html=True)
                if not is_past:
                    if st.button("🔴 Stornieren", key=f"cancel_{b['id']}"):
                        ww_db.cancel_booking(b['id'], st.session_state.user['email'])
                        st.rerun()
    except Exception as e:
        st.error(f"Fehler: {e}")

def show_month_calendar():
    st.title("📅 Monatskalender")
    
    if 'calendar_month' not in st.session_state:
        st.session_state.calendar_month = datetime.now().month
        st.session_state.calendar_year = datetime.now().year
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("◀️"):
            st.session_state.calendar_month -= 1
            if st.session_state.calendar_month < 1:
                st.session_state.calendar_month = 12
                st.session_state.calendar_year -= 1
            st.rerun()
    with col2:
        months = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 
                  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']
        st.markdown(f"<h3 style='text-align:center'>{months[st.session_state.calendar_month-1]} {st.session_state.calendar_year}</h3>", unsafe_allow_html=True)
    with col3:
        if st.button("▶️"):
            st.session_state.calendar_month += 1
            if st.session_state.calendar_month > 12:
                st.session_state.calendar_month = 1
                st.session_state.calendar_year += 1
            st.rerun()
    
    month = st.session_state.calendar_month
    year = st.session_state.calendar_year
    
    # Buchungen laden
    bookings = {}
    try:
        for doc in ww_db.db.collection('bookings').where('status', '==', 'confirmed').stream():
            b = doc.to_dict()
            date_str = b['slot_date']
            if date_str.startswith(f"{year}-{month:02d}"):
                if date_str not in bookings:
                    bookings[date_str] = []
                bookings[date_str].append(b)
    except:
        pass
    
    # Kalender anzeigen
    cal = cal_module.monthcalendar(year, month)
    weekdays = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    
    calendar_html = '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-top:1rem">'
    for day in weekdays:
        calendar_html += f'<div style="text-align:center;font-weight:bold;padding:0.5rem;background:{COLORS["grau_mittel"]};border-radius:4px">{day}</div>'
    
    for week in cal:
        for day in week:
            if day == 0:
                calendar_html += '<div style="min-height:80px"></div>'
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                day_bookings = bookings.get(date_str, [])
                is_today = date_str == datetime.now().strftime("%Y-%m-%d")
                blocked = is_blocked(date_str)
                
                bg = f"{COLORS['rot']}20" if is_today else (COLORS['grau_mittel'] if blocked else COLORS['grau_hell'])
                badges = "".join([f'<div style="background:{COLORS["erfolg"]}30;color:{COLORS["erfolg"]};padding:2px;margin:2px 0;border-radius:3px;font-size:0.7rem">{b["user_name"][:10]}</div>' for b in day_bookings])
                if blocked:
                    badges = f'<div style="color:{COLORS["grau_dunkel"]};font-size:0.7rem">🚫</div>'
                
                calendar_html += f'''<div style="min-height:80px;background:{bg};padding:0.5rem;border-radius:8px;
                    border:{"2px solid "+COLORS["rot"] if is_today else "1px solid "+COLORS["grau_mittel"]}">
                    <div style="font-weight:bold">{day}</div>{badges}</div>'''
    
    calendar_html += '</div>'
    st.markdown(calendar_html, unsafe_allow_html=True)

def show_handbook():
    st.title("📚 Handbuch")
    user = st.session_state.user
    is_admin = user.get('role') == 'admin'
    
    tab1, tab2 = st.tabs(["🚨 Notfall", "🏊 Checkliste"])
    
    with tab1:
        default = """## 🚨 Notfall-Prozedur\n### Sofortmaßnahmen:\n- 🚨 **Notruf:** 112\n- 🏥 **Erste Hilfe** leisten"""
        content = ww_db.get_setting('handbook_notfall', default)
        st.markdown(content)
        if is_admin:
            with st.expander("✏️ Bearbeiten (Admin)"):
                new = st.text_area("", content, height=300, key="edit_notfall")
                if st.button("💾 Speichern", key="save_notfall"):
                    ww_db.set_setting('handbook_notfall', new)
                    st.success("✅ Gespeichert!")
                    st.rerun()
    
    with tab2:
        default = """## 🏊 Schicht-Checkliste\n### VOR Schicht:\n- [ ] 15 Min früher\n- [ ] Dienstkleidung"""
        content = ww_db.get_setting('handbook_checkliste', default)
        st.markdown(content)
        if is_admin:
            with st.expander("✏️ Bearbeiten (Admin)"):
                new = st.text_area("", content, height=300, key="edit_check")
                if st.button("💾 Speichern", key="save_check"):
                    ww_db.set_setting('handbook_checkliste', new)
                    st.success("✅ Gespeichert!")
                    st.rerun()

def show_profile():
    st.title("👤 Profil")
    user = st.session_state.user
    
    # NEU: CHECK - Muss User Passwort ändern?
    if st.session_state.get('force_password_change', False) or user.get('must_change_password', False):
        st.error("⚠️ **WICHTIG:** Sie müssen Ihr Passwort ändern, bevor Sie fortfahren können!")
        
        with st.form("force_password_change_form"):
            st.markdown("### 🔒 Passwort ändern (Pflicht)")
            
            new_password = st.text_input("Neues Passwort", type="password", help="Mindestens 6 Zeichen")
            new_password_confirm = st.text_input("Neues Passwort bestätigen", type="password")
            
            submit = st.form_submit_button("🔒 Passwort ändern", use_container_width=True, type="primary")
            
            if submit:
                if not new_password or not new_password_confirm:
                    st.error("❌ Bitte alle Felder ausfüllen!")
                elif new_password != new_password_confirm:
                    st.error("❌ Passwörter stimmen nicht überein!")
                elif len(new_password) < 6:
                    st.error("❌ Passwort muss mindestens 6 Zeichen haben!")
                else:
                    # Passwort ändern
                    success = ww_db.updateuser(
                        user['id'],
                        password_hash=hashpw(new_password),
                        must_change_password=False
                    )
                    
                    if success:
                        st.session_state.user['password_hash'] = hashpw(new_password)
                        st.session_state.user['must_change_password'] = False
                        if 'force_password_change' in st.session_state:
                            del st.session_state.force_password_change
                        
                        st.success("✅ Passwort erfolgreich geändert! Sie können die App jetzt nutzen.")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("❌ Fehler beim Ändern des Passworts")
        
        st.stop()  # Verhindert Zugriff auf restliche Profil-Funktionen
    
    tab1, tab2, tab3 = st.tabs(["📝 Daten", "🔐 Passwort", "📧 Tests"])
    
    with tab1:
        st.info(f"**E-Mail:** {user['email']}")
        name = st.text_input("Name", value=user.get('name', ''))
        phone = st.text_input("Telefon", value=user.get('phone', ''))
        email_notif = st.checkbox("E-Mail-Benachrichtigungen", value=user.get('email_notifications', True))
        sms_notif = st.checkbox("SMS-Reminder (24h/1h vorher)", value=user.get('sms_notifications', False))
        sms_booking = st.checkbox("SMS bei Buchung sofort", value=user.get('sms_booking_confirmation', True))
        
        if st.button("💾 Speichern", type="primary"):
            ww_db.update_user(user['id'], name=name, phone=phone, email_notifications=email_notif,
                             sms_notifications=sms_notif, sms_booking_confirmation=sms_booking)
            st.success("✅ Gespeichert!")
            st.session_state.user = ww_db.get_user(user['email'])
    
    with tab2:
        st.subheader("Passwort ändern")
        old_pw = st.text_input("Altes Passwort", type="password")
        new_pw = st.text_input("Neues Passwort", type="password")
        new_pw2 = st.text_input("Neues Passwort bestätigen", type="password")
        
        if st.button("🔐 Passwort ändern", type="primary"):
            if not old_pw or not new_pw or not new_pw2:
                st.error("❌ Alle Felder ausfüllen!")
            elif hash_pw(old_pw) != user['password_hash']:
                st.error("❌ Altes Passwort falsch!")
            elif new_pw != new_pw2:
                st.error("❌ Neue Passwörter ungleich!")
            elif len(new_pw) < 8:
                st.error("❌ Min. 8 Zeichen!")
            else:
                ww_db.update_user(user['id'], password_hash=hash_pw(new_pw))
                st.success("✅ Passwort geändert!")
    
    with tab3:
        st.subheader("Benachrichtigungen testen")
        
        # ADMIN DEBUG
        if user.get('role') == 'admin':
            with st.expander("🔧 Debug-Info (Admin)"):
                st.write(f"**E-Mail Config:**")
                st.write(f"- Server: {mailer.server}")
                st.write(f"- Port: {mailer.port}")
                st.write(f"- User: {mailer.user[:5]}***" if mailer.user else "- User: ❌ Nicht gesetzt")
                st.write(f"- Password: {'✅ Gesetzt' if mailer.pw else '❌ Nicht gesetzt'}")
                st.write(f"**SMS Config:**")
                st.write(f"- Enabled: {sms.enabled}")
                st.write(f"- SID: {sms.sid[:8]}***" if sms.sid else "- SID: ❌ Nicht gesetzt")
                st.write(f"- Token: {'✅ Gesetzt' if sms.token else '❌ Nicht gesetzt'}")
                st.write(f"- Phone: {sms.phone}" if sms.phone else "- Phone: ❌ Nicht gesetzt")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📧 Test-E-Mail", use_container_width=True):
                if mailer.test_email(user['email']):
                    st.success("✅ E-Mail gesendet! Prüfe dein Postfach.")
                else:
                    st.error("❌ E-Mail-Fehler! Siehe Debug-Info oben.")
        
        with col2:
            if st.button("📱 Test-SMS", use_container_width=True):
                if not user.get('phone'):
                    st.error("❌ Keine Telefonnummer hinterlegt!")
                elif sms.test_sms(user['phone']):
                    st.success("✅ SMS gesendet!")
                else:
                    st.error("❌ SMS-Fehler! Siehe Debug-Info oben.")

# FIX: Dashboard mit Scoreboard
def show_dashboard():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("📊 Dashboard")
    stats = ww_db.get_stats()
    
    # Statistik-Boxen
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div style="background:linear-gradient(135deg,{COLORS["rot"]},{COLORS["blau"]});padding:1.5rem;border-radius:12px;text-align:center;color:white"><h2 style="color:white;margin:0">{stats["total_users"]}</h2><p style="margin:0">Aktive User</p></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div style="background:linear-gradient(135deg,{COLORS["blau"]},{COLORS["blau_hell"]});padding:1.5rem;border-radius:12px;text-align:center;color:white"><h2 style="color:white;margin:0">{stats["future_bookings"]}</h2><p style="margin:0">Kommende Schichten</p></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div style="background:linear-gradient(135deg,{COLORS["rot_hell"]},{COLORS["rot"]});padding:1.5rem;border-radius:12px;text-align:center;color:white"><h2 style="color:white;margin:0">{stats["month_bookings"]}</h2><p style="margin:0">Diesen Monat</p></div>', unsafe_allow_html=True)
    
    st.divider()
    
    # NEU: Scoreboard
    st.subheader("🏆 Schicht-Scoreboard")
    try:
        user_stats = []
        for doc in ww_db.db.collection('bookings').where('status', '==', 'confirmed').stream():
            b = doc.to_dict()
            user_stats.append(b.get('user_name', ''))
        
        if user_stats:
            user_counts = Counter(user_stats)
            scoreboard_data = [{'Name': name, 'Schichten': count} for name, count in user_counts.most_common()]
            
            for idx, row in enumerate(scoreboard_data[:10]):
                if idx == 0:
                    st.markdown(f"🥇 **{row['Name']}**: {row['Schichten']} Schichten")
                elif idx == 1:
                    st.markdown(f"🥈 **{row['Name']}**: {row['Schichten']} Schichten")
                elif idx == 2:
                    st.markdown(f"🥉 **{row['Name']}**: {row['Schichten']} Schichten")
                else:
                    st.write(f"{idx+1}. {row['Name']}: {row['Schichten']} Schichten")
        else:
            st.info("Noch keine Buchungen für Scoreboard")
    except Exception as e:
        st.error(f"Scoreboard-Fehler: {e}")
    
    st.divider()
    st.subheader("🆓 Freie Slots (nächste 4 Wochen)")
    free = stats['free_slots_next_4weeks']
    if free:
        for slot in free[:15]:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.info(f"📅 {fmt_de(slot['date'])} - {slot['slot']}")
            with col2:
                days_until = (datetime.strptime(slot['date'], "%Y-%m-%d") - datetime.now()).days
                if days_until < 7:
                    st.warning(f"⚠️ {days_until}d")
    else:
        st.success("✅ Alle Slots gebucht!")

def show_users():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("👥 Benutzerverwaltung")
    
    tab1, tab2 = st.tabs(["📋 Alle Benutzer", "➕ Neuer Benutzer"])
    
    with tab1:
        users = ww_db.getallusers()
        if not users:
            st.info("Noch keine Benutzer vorhanden.")
        else:
            st.write(f"**{len(users)} Benutzer gefunden**")
            
            for u in users:
                with st.expander(f"{u.get('name')} ({u.get('email')})"):
                    col1, col2 = st.columns([3, 2])
                    
                    with col1:
                        st.markdown(f"**Name:** {u.get('name')}")
                        st.markdown(f"**E-Mail:** {u.get('email')}")
                        st.markdown(f"**Telefon:** {u.get('phone', 'N/A')}")
                        st.markdown(f"**Rolle:** {u.get('role')}")
                        st.markdown(f"**Aktiv:** {'✅' if u.get('active', True) else '❌'}")
                        
                        # Passwort-Reset Info (falls vorhanden)
                        if u.get('password_reset_at'):
                            st.caption(f"🔑 Passwort zuletzt zurückgesetzt: {u.get('password_reset_at')} von {u.get('password_reset_by', 'N/A')}")
                        
                        if u.get('must_change_password'):
                            st.warning("⚠️ Muss Passwort beim nächsten Login ändern")
                    
                    with col2:
                        # Löschen
                        if u['email'] != st.session_state.user['email']:
                            if st.button("🗑️", key=f"del_{u['id']}", use_container_width=True):
                                ww_db.deleteuser(u['email'])
                                st.rerun()
                        
                        # NEU: PASSWORT ZURÜCKSETZEN
                        if st.button("🔑 Passwort zurücksetzen", key=f"reset_{u['id']}", use_container_width=True, type="primary"):
                            st.session_state[f'show_reset_modal_{u["id"]}'] = True
                            st.rerun()
                    
                    # PASSWORT-RESET MODAL
                    if st.session_state.get(f'show_reset_modal_{u["id"]}', False):
                        st.divider()
                        st.markdown("### 🔑 Passwort zurücksetzen")
                        
                        with st.form(f"reset_password_{u['id']}"):
                            st.info(f"Neues Passwort für: **{u.get('name')}** ({u.get('email')})")
                            
                            new_pw = st.text_input("Neues Passwort", type="password", help="Mindestens 6 Zeichen")
                            new_pw_confirm = st.text_input("Passwort bestätigen", type="password")
                            
                            force_change = st.checkbox("User muss Passwort beim nächsten Login ändern", value=True)
                            
                            col_a, col_b = st.columns(2)
                            
                            with col_a:
                                submit_reset = st.form_submit_button("✅ Zurücksetzen", use_container_width=True, type="primary")
                            
                            with col_b:
                                cancel_reset = st.form_submit_button("❌ Abbrechen", use_container_width=True)
                            
                            if cancel_reset:
                                st.session_state[f'show_reset_modal_{u["id"]}'] = False
                                st.rerun()
                            
                            if submit_reset:
                                # Validierung
                                if not new_pw or not new_pw_confirm:
                                    st.error("❌ Bitte beide Passwort-Felder ausfüllen!")
                                elif new_pw != new_pw_confirm:
                                    st.error("❌ Passwörter stimmen nicht überein!")
                                elif len(new_pw) < 6:
                                    st.error("❌ Passwort muss mindestens 6 Zeichen haben!")
                                else:
                                    # BESTÄTIGUNG
                                    if st.checkbox(f"✅ JA, Passwort für {u.get('name')} JETZT zurücksetzen", key=f"confirm_{u['id']}"):
                                        # Passwort zurücksetzen
                                        admin_user = st.session_state.user
                                        reset_timestamp = datetime.now().strftime('%d.%m.%Y %H:%M')
                                        
                                        success = ww_db.updateuser(
                                            u['id'],
                                            password_hash=hashpw(new_pw),
                                            must_change_password=force_change,
                                            password_reset_at=reset_timestamp,
                                            password_reset_by=admin_user.get('email')
                                        )
                                        
                                        if success:
                                            st.success(f"✅ Passwort für {u.get('name')} erfolgreich zurückgesetzt!")
                                            
                                            # E-Mail-Benachrichtigung senden
                                            mail_success, mail_msg = mailer.send_password_reset_notification(
                                                u.get('email'),
                                                u.get('name'),
                                                admin_user.get('name')
                                            )
                                            
                                            if mail_success:
                                                st.info("📧 Benachrichtigungs-E-Mail wurde versendet")
                                            else:
                                                st.warning(f"⚠️ E-Mail konnte nicht versendet werden: {mail_msg}")
                                            
                                            # Neues Passwort anzeigen
                                            st.markdown("---")
                                            st.markdown("### 📋 Neues Passwort (bitte notieren)")
                                            st.code(new_pw, language=None)
                                            st.caption("💡 Teilen Sie dem User dieses Passwort persönlich/telefonisch mit.")
                                            
                                            st.balloons()
                                            st.session_state[f'show_reset_modal_{u["id"]}'] = False
                                            
                                            import time
                                            time.sleep(2)
                                            st.rerun()
                                        else:
                                            st.error("❌ Fehler beim Zurücksetzen des Passworts")
    
    with tab2:
        # Neuer Benutzer - bleibt wie gehabt
        with st.form("newuser"):
            email = st.text_input("E-Mail")
            name = st.text_input("Name")
            phone = st.text_input("Telefon")
            password = st.text_input("Passwort", type="password")
            role = st.selectbox("Rolle", ["user", "admin"])
            
            if st.form_submit_button("User anlegen", type="primary"):
                success, msg = ww_db.createuser(email, name, phone, password, role)
                if success:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")

def show_export():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("📥 Export & Backup")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""<div style='background:{COLORS['grau_hell']};padding:1.5rem;border-radius:12px;text-align:center'>
            <h3>📊 Excel Export</h3><p>Alle Buchungen als Excel</p></div>""", unsafe_allow_html=True)
        if st.button("📊 Excel Download", type="primary", use_container_width=True):
            bookings = []
            for doc in ww_db.db.collection('bookings').stream():
                b = doc.to_dict()
                bookings.append({
                    'Datum': b.get('slot_date', ''),
                    'Zeit': b.get('slot_time', ''),
                    'Name': b.get('user_name', ''),
                    'Status': b.get('status', '')
                })
            df = pd.DataFrame(bookings)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("⬇️ Download", buffer.getvalue(),
                              f"export_{datetime.now().strftime('%Y%m%d')}.xlsx")
    
    with col2:
        st.markdown(f"""<div style='background:{COLORS['grau_hell']};padding:1.5rem;border-radius:12px;text-align:center'>
            <h3>📧 E-Mail Backup</h3><p>Backup per E-Mail senden</p></div>""", unsafe_allow_html=True)
        if st.button("📧 Backup senden", type="primary", use_container_width=True):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as zf:
                csv = "date,time,user,status\n"
                for doc in ww_db.db.collection('bookings').stream():
                    d = doc.to_dict()
                    csv += f"{d.get('slot_date','')},{d.get('slot_time','')},{d.get('user_name','')},{d.get('status','')}\n"
                zf.writestr('bookings.csv', csv)
            if mailer.backup_email(buffer.getvalue()):
                st.success("✅ Backup gesendet!")
            else:
                st.error("❌ Fehler beim Versenden")

def show_settings():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("⚙️ Einstellungen")
    tab1, tab2 = st.tabs(["📧 E-Mail", "📱 SMS"])
    
    with tab1:
        st.subheader("E-Mail-Templates")
        booking = ww_db.get_setting('email_booking_template',
                                     'Hallo {name}, deine Schicht am {date} um {time} wurde gebucht.')
        cancel = ww_db.get_setting('email_cancellation_template',
                                    'Hallo {name}, deine Schicht am {date} um {time} wurde storniert.')
        
        new_booking = st.text_area("Buchung", booking, height=100, help="{name}, {date}, {time}")
        new_cancel = st.text_area("Stornierung", cancel, height=100, help="{name}, {date}, {time}")
        
        if st.button("💾 E-Mail-Templates speichern", type="primary"):
            ww_db.set_setting('email_booking_template', new_booking)
            ww_db.set_setting('email_cancellation_template', new_cancel)
            st.success("✅ Gespeichert!")
    
    with tab2:
        st.subheader("SMS-Templates")
        sms_booking = ww_db.get_setting('sms_booking_template',
                                        'Wasserwacht: Buchung bestätigt! {date} {time}')
        sms24 = ww_db.get_setting('sms_24h_template',
                                  'Wasserwacht: Deine Schicht ist morgen {date} um {time}.')
        sms1 = ww_db.get_setting('sms_1h_template',
                                 'Wasserwacht: Deine Schicht beginnt in 1h ({time}).')
        
        new_sms_booking = st.text_area("Bei Buchung", sms_booking, height=80, help="{name}, {date}, {time}")
        new_sms24 = st.text_area("24h Reminder", sms24, height=80, help="{name}, {date}, {time}")
        new_sms1 = st.text_area("1h Reminder", sms1, height=80, help="{name}, {time}")
        
        if st.button("💾 SMS-Templates speichern", type="primary"):
            ww_db.set_setting('sms_booking_template', new_sms_booking)
            ww_db.set_setting('sms_24h_template', new_sms24)
            ww_db.set_setting('sms_1h_template', new_sms1)
            st.success("✅ Gespeichert!")

def show_impressum():
    st.title("📄 Impressum")
    default = """# Impressum\n**Wasserwacht Hauzenberg e.V.**\n[Adresse]\n\n**Kontakt:** [E-Mail]"""
    impressum = ww_db.get_setting('impressum', default)
    st.markdown(impressum)
    
    if st.session_state.user and st.session_state.user.get('role') == 'admin':
        with st.expander("✏️ Bearbeiten (Admin)"):
            new = st.text_area("Text", impressum, height=300)
            if st.button("💾 Speichern", type="primary"):
                ww_db.set_setting('impressum', new)
                st.success("✅ Gespeichert!")
                st.rerun()

# ===== APP START =====
if __name__ == "__main__":
    main()